#!/usr/bin/env python3
"""
Mini Project 4.2 - Multi-Rate Environmental Monitoring Pipeline
with Timing-Compliance Reporting
Real-Time Systems, Unit 4 Lab

Story
-----
One small gateway node reads several sensors. Each sensor must be read at its own
required period. The gateway has ONE processing loop, so it can only read one
sensor at a time and must decide who goes first. Every read takes a random amount
of time with an occasional very long one (an "overrun"). We measure how often each
sensor was read on time, late or not at all, and how late the threshold alerts are.

Scheduling rules compared (all documented in the README and report)
  FP  : fixed priority, shortest required period first (rate-monotonic order)
  EDF : earliest deadline first among the due streams
  RR  : round-robin, the due streams take turns in a fixed cyclic order

Run:   python3 env_monitor_pipeline.py
Needs: Python 3.10+, matplotlib. Everything else is standard library.
"""

import bisect
import csv
import math
import os
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(HERE, "figures")
RES_DIR = os.path.join(HERE, "results")
os.makedirs(FIG_DIR, exist_ok=True)
os.makedirs(RES_DIR, exist_ok=True)

# Colour-blind-safe colours (Okabe-Ito). The SAME three colours mean the SAME
# sample class in every figure.
C_ON = "#0072B2"     # on-time
C_LATE = "#E69F00"   # late
C_MISS = "#D55E00"   # missed
C_FP, C_EDF, C_RR = "#0072B2", "#009E73", "#CC79A7"   # scheduling rules
C_SIG = "#555555"

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "legend.frameon": False,
})

HORIZON = 60.0          # simulated seconds
TOLERANCE = 0.20        # a sample is ON TIME if it starts within 20% of its period after its due time
P_TAIL = 0.08           # probability that a read hits the long tail (overrun)
TAIL_RANGE = (0.040, 0.160)   # duration of an overrunning read (s)


# ----------------------------------------------------------------------------
# 1. Synthetic sensor signals
# ----------------------------------------------------------------------------
def _pulses(t, centres, sigma, height):
    return sum(height * math.exp(-((t - c) ** 2) / (2.0 * sigma ** 2)) for c in centres)


def temperature(t):   # slow drift: alert when it gets too hot
    return 24.0 + 5.5 * math.sin(2 * math.pi * t / 19.0) + 0.6 * math.sin(2 * math.pi * t / 3.7 + 0.5)


def humidity(t):      # slower drift: alert when it gets too humid
    return 55.0 + 18.0 * math.sin(2 * math.pi * t / 27.0 + 0.2) + 2.0 * math.sin(2 * math.pi * t / 5.3)


AQ_EVENTS = [6.3, 17.8, 31.2, 38.9, 52.4]


def air_quality(t):   # background + short pollution spikes (about 0.8 s above threshold)
    return 35.0 + 4.0 * math.sin(2 * math.pi * t / 11.0) + _pulses(t, AQ_EVENTS, 0.35, 110.0)


VIB_EVENTS = [2.1, 5.7, 9.4, 14.2, 18.8, 22.5, 27.9, 33.3, 41.0, 47.6, 55.1]


def vibration(t):     # fast stream: short bursts (about 0.1 s above threshold)
    return 0.05 * math.sin(2 * math.pi * 13.0 * t) + _pulses(t, VIB_EVENTS, 0.06, 1.2)


@dataclass
class Stream:
    name: str
    period: float                 # required sampling period (s)
    c_range: tuple                # normal read time range (s)
    signal: Callable[[float], float]
    threshold: float
    unit: str
    _exc: list = field(default=None, repr=False)

    def excursions(self, horizon=HORIZON, dt=0.0005):
        """Exact intervals [rise, fall) where the TRUE signal is >= threshold."""
        if self._exc is None:
            out, above, rise = [], False, 0.0
            prev_t = 0.0
            for i in range(int(horizon / dt) + 1):
                t = i * dt
                now = self.signal(t) >= self.threshold
                if now and not above:
                    lo, hi = prev_t, t
                    for _ in range(40):
                        mid = 0.5 * (lo + hi)
                        if self.signal(mid) >= self.threshold:
                            hi = mid
                        else:
                            lo = mid
                    rise, above = hi, True
                elif above and not now:
                    lo, hi = prev_t, t
                    for _ in range(40):
                        mid = 0.5 * (lo + hi)
                        if self.signal(mid) >= self.threshold:
                            lo = mid
                        else:
                            hi = mid
                    out.append((rise, lo))
                    above = False
                prev_t = t
            self._exc = out
        return self._exc


S_TEMP = Stream("Temperature", 0.100, (0.004, 0.008), temperature, 28.5, "degC")
S_HUM = Stream("Humidity", 0.240, (0.006, 0.012), humidity, 68.0, "%RH")
S_AIR = Stream("Air quality", 0.500, (0.015, 0.030), air_quality, 90.0, "ug/m3")
S_VIB = Stream("Vibration (fast)", 0.050, (0.003, 0.006), vibration, 0.8, "g")

LOADS = {
    "3 streams": [S_TEMP, S_HUM, S_AIR],
    "4 streams": [S_TEMP, S_HUM, S_AIR, S_VIB],
}
POLICIES = ["FP", "EDF", "RR"]
POLICY_NAMES = {"FP": "fixed priority (shortest period first)",
                "EDF": "earliest deadline first",
                "RR": "round-robin"}


# ----------------------------------------------------------------------------
# 2. Workload (the random read times) - shared by all policies
# ----------------------------------------------------------------------------
def make_workload(streams, seed):
    """Pre-draw the read duration of every job of every stream, so that every
    scheduling rule faces EXACTLY the same random workload (fair comparison)."""
    work = []
    for i, s in enumerate(streams):
        rng = random.Random(seed * 100 + hash_name(s.name))
        n_jobs = int(HORIZON / s.period + 1e-9)
        c, tail = [], []
        for _ in range(n_jobs):
            u, c_norm, c_tail = rng.random(), rng.uniform(*s.c_range), rng.uniform(*TAIL_RANGE)
            tail.append(u < P_TAIL)
            c.append(c_tail if u < P_TAIL else c_norm)
        work.append({"c": c, "tail": tail, "n_jobs": n_jobs})
    return work


def hash_name(name):   # stable small integer per stream name (Python's hash() is randomised)
    return sum((k + 1) * ord(ch) for k, ch in enumerate(name)) % 1000


# ----------------------------------------------------------------------------
# 3. The scheduler: ONE loop, ONE sensor read at a time (non-preemptive)
# ----------------------------------------------------------------------------
def run_scheduler(streams, work, policy):
    """Simulated-time loop.

    At any moment t the loop is free it looks at every stream. A stream is DUE if
    its most recent release (job j = floor(t / period)) has not been read yet.
    Older unread releases are never read: they are MISSED (a fresh reading is more
    useful than a stale one). Then the policy picks ONE due stream and reads it;
    the clock advances by that read's random duration.
    """
    n = len(streams)
    last = [-1] * n
    rec = [[] for _ in streams]          # per stream: (job, release, start, finish)
    t, busy, rr = 0.0, 0.0, 0
    prio = sorted(range(n), key=lambda i: streams[i].period)
    while t < HORIZON:
        due = []
        for i, s in enumerate(streams):
            j = int(t / s.period + 1e-9)
            if j > last[i] and j < work[i]["n_jobs"]:
                due.append((i, j))
        if not due:
            t = min((int(t / s.period + 1e-9) + 1) * s.period for s in streams)
            continue
        due_idx = {i: j for i, j in due}
        if policy == "FP":
            i = next(k for k in prio if k in due_idx)
        elif policy == "EDF":
            i = min(due_idx, key=lambda k: ((due_idx[k] + 1) * streams[k].period, streams[k].period))
        elif policy == "RR":
            i = next((rr + d) % n for d in range(n) if (rr + d) % n in due_idx)
            rr = (i + 1) % n
        else:
            raise ValueError(policy)
        j = due_idx[i]
        c = work[i]["c"][j]
        rec[i].append((j, j * streams[i].period, t, t + c))
        last[i] = j
        busy += c
        t += c
    return rec, busy / HORIZON


# ----------------------------------------------------------------------------
# 4. Compliance report and alerts
# ----------------------------------------------------------------------------
def classify(stream, rec_i):
    """Return per-sample class list and the counts."""
    cls = []
    for j, rel, start, fin in rec_i:
        cls.append("on-time" if start - rel <= TOLERANCE * stream.period + 1e-12 else "late")
    return cls


def compliance(stream, rec_i, n_jobs):
    cls = classify(stream, rec_i)
    on, late = cls.count("on-time"), cls.count("late")
    missed = n_jobs - len(rec_i)
    starts = [r[2] for r in rec_i]
    over = [max(0.0, b - a - stream.period) for a, b in zip(starts, starts[1:])]
    return {
        "required": n_jobs, "on_time": on, "late": late, "missed": missed,
        "pct_on": 100.0 * on / n_jobs, "pct_late": 100.0 * late / n_jobs, "pct_missed": 100.0 * missed / n_jobs,
        "mean_over": statistics.mean(over) if over else 0.0, "max_over": max(over) if over else 0.0,
    }


def alerts(stream, rec_i):
    """For every true excursion above the threshold: did a read land inside it?
    Logs the TRUE crossing time and the DETECTION time (end of the read that saw it)."""
    starts = [r[2] for r in rec_i]
    out = []
    for rise, fall in stream.excursions():
        k = bisect.bisect_left(starts, rise)
        if k < len(starts) and starts[k] <= fall:
            det = rec_i[k][3]
            out.append({"true_time": rise, "detect_time": det, "latency": det - rise, "missed": False})
        else:
            out.append({"true_time": rise, "detect_time": None, "latency": None, "missed": True})
    return out


def evaluate_one(streams, policy, seed):
    work = make_workload(streams, seed)
    rec, util = run_scheduler(streams, work, policy)
    res = []
    for i, s in enumerate(streams):
        comp = compliance(s, rec[i], work[i]["n_jobs"])
        al = alerts(s, rec[i])
        lat = [a["latency"] for a in al if not a["missed"]]
        comp.update({"alerts": len(al), "alerts_missed": sum(a["missed"] for a in al),
                     "alert_lat_mean": statistics.mean(lat) if lat else float("nan"),
                     "alert_lat_max": max(lat) if lat else float("nan")})
        res.append(comp)
    return rec, work, res, util


# ----------------------------------------------------------------------------
# 5. Tables
# ----------------------------------------------------------------------------
def write_table(name, header, rows, note=""):
    with open(os.path.join(RES_DIR, name + ".csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    with open(os.path.join(RES_DIR, name + ".md"), "w") as fh:
        if note:
            fh.write(note + "\n\n")
        fh.write("| " + " | ".join(header) + " |\n")
        fh.write("|" + "|".join("---" for _ in header) + "|\n")
        for r in rows:
            fh.write("| " + " | ".join(str(x) for x in r) + " |\n")


def ms(x):
    return "n/a" if x != x else f"{x * 1000:.1f}"


# ----------------------------------------------------------------------------
# 6. Figures
# ----------------------------------------------------------------------------
def fig_signals(streams, rec, work, tag, title, window=(0.0, 30.0)):
    """Figure 1 of each configuration: each stream's TRUE signal, threshold, the
    serviced samples (on-time / late) and the missed releases."""
    n = len(streams)
    fig, axes = plt.subplots(n, 1, figsize=(9.5, 2.1 * n + 1.0), sharex=True)
    t0, t1 = window
    for ax, s, r in zip(axes, streams, rec):
        tt = [t0 + i * 0.01 for i in range(int((t1 - t0) / 0.01) + 1)]
        ax.plot(tt, [s.signal(t) for t in tt], color=C_SIG, lw=1.0)
        ax.axhline(s.threshold, color=C_SIG, ls=":", lw=0.9)
        served = {j for j, *_ in r}
        on_x, on_y, la_x, la_y = [], [], [], []
        for j, rel, start, fin in r:
            if not (t0 <= start <= t1):
                continue
            on = start - rel <= TOLERANCE * s.period + 1e-12
            (on_x if on else la_x).append(start)
            (on_y if on else la_y).append(s.signal(start))
        ms_x = [j * s.period for j in range(work[streams.index(s)]["n_jobs"])
                if j not in served and t0 <= j * s.period <= t1]
        ax.plot(on_x, on_y, "o", ms=2.6, color=C_ON, ls="none", label="on time")
        ax.plot(la_x, la_y, "^", ms=4.2, color=C_LATE, ls="none", label="late")
        ax.plot(ms_x, [s.signal(x) for x in ms_x], "x", ms=5, mew=1.3, color=C_MISS, ls="none", label="missed")
        for rise, fall in s.excursions():
            if t0 <= rise <= t1:
                ax.axvspan(rise, min(fall, t1), color=C_SIG, alpha=0.12, lw=0)
        ax.set_ylabel(f"{s.name} ({s.unit})\nrequired period {s.period*1000:.0f} ms", fontsize=7.5)
    axes[0].set_title(title, loc="left", fontsize=10, fontweight="bold")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper right", ncol=3, fontsize=8, bbox_to_anchor=(0.99, 0.995))
    axes[-1].set_xlabel("time (s)   [first 30 s shown; grey bands = true periods above the alert threshold]")
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    fig.savefig(os.path.join(FIG_DIR, f"{tag}_fig1_signals_and_samples.png"))
    plt.close(fig)


def fig_counts(streams, res, tag, title):
    """Figure 2 of each configuration: on-time / late / missed per stream."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 0.7 * len(streams) + 2.4),
                                   gridspec_kw={"width_ratios": [1.15, 1]})
    names = [s.name for s in streams]
    y = list(range(len(streams)))[::-1]
    w = 0.26
    for off, key, col, lab in ((w, "on_time", C_ON, "on time"), (0, "late", C_LATE, "late"),
                               (-w, "missed", C_MISS, "missed")):
        vals = [r[key] for r in res]
        bars = ax1.barh([yy + off for yy in y], vals, height=w * 0.92, color=col, label=lab)
        for b, v in zip(bars, vals):
            ax1.text(b.get_width() + max(r["required"] for r in res) * 0.01, b.get_y() + b.get_height() / 2,
                     str(v), va="center", fontsize=7.5)
    ax1.set_yticks(y)
    ax1.set_yticklabels(names)
    ax1.set_xlabel("number of samples")
    ax1.set_xlim(0, max(r["required"] for r in res) * 1.12)
    ax1.grid(axis="y", visible=False)
    ax1.legend(loc="lower right", fontsize=8)
    ax1.set_title("Counts", loc="left", fontsize=9, fontweight="bold")
    # percentage stacked
    left = [0.0] * len(streams)
    for key, col in (("pct_on", C_ON), ("pct_late", C_LATE), ("pct_missed", C_MISS)):
        vals = [r[key] for r in res]
        ax2.barh(y, vals, left=left, height=0.55, color=col, edgecolor="white", linewidth=1.0)
        for yy, v, lf in zip(y, vals, left):
            if v >= 6:
                ax2.text(lf + v / 2, yy, f"{v:.0f}%", ha="center", va="center", fontsize=7.5, color="white")
        left = [a + b for a, b in zip(left, vals)]
    ax2.set_yticks(y)
    ax2.set_yticklabels([""] * len(y))
    ax2.set_xlim(0, 100)
    ax2.set_xlabel("share of required samples (%)")
    ax2.grid(axis="y", visible=False)
    ax2.set_title("Share", loc="left", fontsize=9, fontweight="bold")
    fig.suptitle(title, x=0.01, ha="left", fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, f"{tag}_fig2_on_time_late_missed.png"))
    plt.close(fig)


def fig_compare(agg):
    """Extra figure: % on-time per stream, three rules side by side, for both loads."""
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.9), sharey=True)
    cols = {"FP": C_FP, "EDF": C_EDF, "RR": C_RR}
    for ax, (load, streams) in zip(axes, LOADS.items()):
        x = list(range(len(streams)))
        w = 0.26
        for k, pol in enumerate(POLICIES):
            vals = [agg[(load, pol)]["streams"][i]["pct_on"] for i in x]
            bars = ax.bar([xx + (k - 1) * w for xx in x], vals, w * 0.92, color=cols[pol], label=pol)
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}", ha="center", fontsize=7)
        ax.set_xticks(x)
        ax.set_xticklabels([s.name for s in streams], fontsize=8)
        ax.set_ylim(0, 108)
        ax.grid(axis="x", visible=False)
        ax.set_title(f"Load: {load}", loc="left", fontsize=9, fontweight="bold")
    axes[0].set_ylabel("samples on time (%) - mean of 30 runs")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper right", ncol=3, fontsize=8, bbox_to_anchor=(0.99, 0.995))
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(FIG_DIR, "extra_fig3_policy_comparison_on_time.png"))
    plt.close(fig)


# ----------------------------------------------------------------------------
# 7. Main
# ----------------------------------------------------------------------------
SEEDS = list(range(1, 31))


def main():
    print("Mini Project 4.2 - multi-rate environmental monitoring pipeline")
    print(f"horizon {HORIZON:.0f} s, tolerance {TOLERANCE:.0%} of period, long-tail read: "
          f"p = {P_TAIL:.0%}, {TAIL_RANGE[0]*1000:.0f}-{TAIL_RANGE[1]*1000:.0f} ms\n")

    header = ["load", "rule", "stream", "required period (ms)", "required samples", "on time", "late", "missed",
              "% on time", "mean period overrun (ms)", "max period overrun (ms)", "alerts (true events)",
              "alerts missed", "mean alert latency (ms)", "max alert latency (ms)"]
    single_rows, util_rows = [], []
    alert_rows = []
    for load, streams in LOADS.items():
        for pol in POLICIES:
            tag = f"{load.split()[0]}streams_{pol}"
            rec, work, res, util = evaluate_one(streams, pol, seed=1)
            util_rows.append([load, pol, f"{util*100:.1f}"])
            for s, r in zip(streams, res):
                single_rows.append([load, pol, s.name, f"{s.period*1000:.0f}", r["required"], r["on_time"], r["late"],
                                    r["missed"], f"{r['pct_on']:.1f}", ms(r["mean_over"]), ms(r["max_over"]),
                                    r["alerts"], r["alerts_missed"], ms(r["alert_lat_mean"]), ms(r["alert_lat_max"])])
            for s, rc in zip(streams, rec):
                for a in alerts(s, rc):
                    alert_rows.append([load, pol, s.name, f"{a['true_time']:.4f}",
                                       "" if a["missed"] else f"{a['detect_time']:.4f}",
                                       "" if a["missed"] else f"{a['latency']*1000:.1f}", "MISSED" if a["missed"] else "ok"])
            title = f"{load}, {POLICY_NAMES[pol]}"
            fig_signals(streams, rec, work, tag, title)
            fig_counts(streams, res, tag, title)
    write_table("table1_compliance_report_seed1", header, single_rows,
                "Per-stream timing-compliance report, one run (seed 1), 60 s simulated. A sample is ON TIME if its "
                "read starts within 20% of the period after its due time, LATE if it starts later but before the "
                "next due time, MISSED if it is never read before the next due time.")
    write_table("table_cpu_utilisation_seed1", ["load", "rule", "CPU busy (%)"], util_rows,
                "Fraction of the 60 s the gateway loop spent reading sensors (seed 1).")
    write_table("alert_log_seed1", ["load", "rule", "stream", "true crossing time (s)", "detection time (s)",
                                    "alert latency (ms)", "status"], alert_rows,
                "Every true threshold event, the moment it really began, and the moment the gateway raised the alert.")

    # ---- 30-seed robustness table --------------------------------------
    agg, rows2 = {}, []
    for load, streams in LOADS.items():
        for pol in POLICIES:
            per_seed = [evaluate_one(streams, pol, sd) for sd in SEEDS]
            sres = []
            for i, s in enumerate(streams):
                col = [ps[2][i] for ps in per_seed]
                lat = [c["alert_lat_mean"] for c in col if c["alert_lat_mean"] == c["alert_lat_mean"]]
                sres.append({k: statistics.mean(c[k] for c in col) for k in
                             ("pct_on", "pct_late", "pct_missed", "mean_over", "max_over", "alerts", "alerts_missed")})
                sres[-1]["alert_lat_mean"] = statistics.mean(lat) if lat else float("nan")
                sres[-1]["alert_lat_max"] = statistics.mean(c["alert_lat_max"] for c in col
                                                            if c["alert_lat_max"] == c["alert_lat_max"])
                rows2.append([load, pol, s.name, f"{sres[-1]['pct_on']:.1f}", f"{sres[-1]['pct_late']:.1f}",
                              f"{sres[-1]['pct_missed']:.1f}", ms(sres[-1]["mean_over"]), ms(sres[-1]["max_over"]),
                              f"{sres[-1]['alerts_missed']:.2f} / {sres[-1]['alerts']:.0f}",
                              ms(sres[-1]["alert_lat_mean"]), ms(sres[-1]["alert_lat_max"])])
            util = statistics.mean(ps[3] for ps in per_seed)
            agg[(load, pol)] = {"streams": sres, "util": util}
    write_table("table2_compliance_30runs", ["load", "rule", "stream", "% on time", "% late", "% missed",
                "mean period overrun (ms)", "max period overrun (ms, mean of runs)", "alerts missed / true events",
                "mean alert latency (ms)", "max alert latency (ms, mean of runs)"], rows2,
                "Average over 30 independent random workloads. Every rule sees the same workload in each run.")
    write_table("table3_cpu_utilisation_30runs", ["load", "rule", "CPU busy (%)"],
                [[l, p, f"{agg[(l, p)]['util']*100:.1f}"] for (l, p) in agg],
                "Average over 30 runs.")
    fig_compare(agg)

    # ---- which stream suffers most ------------------------------------
    print("Worst stream per configuration (30-run mean, % NOT on time):")
    for (load, pol), v in agg.items():
        worst = max(range(len(v["streams"])), key=lambda i: 100 - v["streams"][i]["pct_on"])
        name = LOADS[load][worst].name
        print(f"  {load:10s} {pol:3s}: {name:18s} {100 - v['streams'][worst]['pct_on']:.1f}%  "
              f"(CPU busy {v['util']*100:.0f}%)")
    print("\nTables written to results/, figures to figures/.")


if __name__ == "__main__":
    main()
