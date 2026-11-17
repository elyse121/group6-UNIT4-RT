#!/usr/bin/env python3
"""
Mini Project 4.3 - Edge-versus-Cloud Latency Simulator for a Real-Time IoT Decision Task
Real-Time Systems, Unit 4 Lab

Story
-----
A sensor reading arrives 10 times per second. For each reading the system must
DECIDE (for example "is this vibration an anomaly that needs immediate action?")
within a deadline of 100 ms. Three architectures are compared on the SAME stream of
readings:

  EDGE   : decide on the device itself. No network, but limited hardware, so the
           computation is slower (and much slower for "hard" decisions).
  CLOUD  : send the reading to a data centre, decide there, send the answer back.
           Fast computation, but the network legs are long-tailed: sometimes a
           congestion spike makes them very slow.
  HYBRID : a quick triage on the device sends easy decisions to the local edge
           path and hard decisions to the cloud.

Run:   python3 edge_vs_cloud_sim.py
Needs: Python 3.10+, matplotlib. Everything else is standard library.
All times are in milliseconds. Results are reproducible (fixed random seed).
"""

import csv
import math
import os
import random
import statistics
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(HERE, "figures")
RES_DIR = os.path.join(HERE, "results")
os.makedirs(FIG_DIR, exist_ok=True)
os.makedirs(RES_DIR, exist_ok=True)

C_EDGE, C_CLOUD, C_HYB = "#0072B2", "#D55E00", "#009E73"   # colour-blind-safe (Okabe-Ito)
C_REF = "#555555"

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "legend.frameon": False,
})

# ----------------------------------------------------------------------------
# Parameters (all in milliseconds)
# ----------------------------------------------------------------------------
N_EVENTS = 20000          # number of sensor readings / decisions
EVENT_PERIOD = 100.0      # a reading every 100 ms (10 Hz)
DEADLINE = 100.0          # the decision must be ready within 100 ms of the reading
P_HARD = 0.20             # 20% of the decisions are "hard"
BASELINE_CONGESTION = 0.20

# Edge: limited local hardware
EDGE_TX = (0.5, 1.5)               # sensor -> edge processor transfer (negligible)
EDGE_EASY = (25.0, 4.0)            # compute time: mean, st.dev.
EDGE_HARD = (90.0, 12.0)           # hard decisions are slow on small hardware

# Cloud: powerful server, long-tailed network
UP_MEDIAN, DOWN_MEDIAN, NET_SIGMA = 18.0, 12.0, 0.30   # log-normal body of each network leg
CLOUD_EASY = (6.0, 1.0)
CLOUD_HARD = (14.0, 2.0)
SPIKE_P0, SPIKE_P1 = 0.005, 0.15   # spike probability per leg = P0 + P1 * congestion
SPIKE_XM0, SPIKE_ALPHA = 30.0, 1.6 # spike size ~ Pareto(x_m = 30*(1+congestion), alpha = 1.6)
SPIKE_CAP = 2000.0                 # network time-out: no spike is longer than 2 s
NET_GROW = 0.6                     # network body grows by (1 + NET_GROW * congestion)

# Hybrid triage
TRIAGE_MS = 2.0
TRIAGE_ACC = 0.95


@dataclass
class Event:
    arrival: float
    hard: bool
    edge_tx: float
    z_edge: float
    z_up: float
    u_sp_up: float
    u_par_up: float
    z_dn: float
    u_sp_dn: float
    u_par_dn: float
    z_comp: float
    u_triage: float


def make_events(n=N_EVENTS, seed=42):
    """One shared stream of events. Every random number needed by ANY architecture
    is drawn here once, so all architectures face exactly the same readings, and
    sweeping the congestion level only changes how those same numbers are used."""
    rng = random.Random(seed)
    ev = []
    for k in range(n):
        ev.append(Event(
            arrival=k * EVENT_PERIOD, hard=rng.random() < P_HARD,
            edge_tx=rng.uniform(*EDGE_TX), z_edge=rng.gauss(0, 1),
            z_up=rng.gauss(0, 1), u_sp_up=rng.random(), u_par_up=rng.random(),
            z_dn=rng.gauss(0, 1), u_sp_dn=rng.random(), u_par_dn=rng.random(),
            z_comp=rng.gauss(0, 1), u_triage=rng.random()))
    return ev


# ----------------------------------------------------------------------------
# The two paths
# ----------------------------------------------------------------------------
def edge_compute(ev: Event) -> float:
    """Time the small local processor needs to decide (short, low variance)."""
    mean, sd = EDGE_HARD if ev.hard else EDGE_EASY
    floor = 40.0 if ev.hard else 8.0
    return max(floor, mean + sd * ev.z_edge)


def simulate_edge(events, subset=None):
    """EDGE latency = waiting for the processor + compute. The processor handles one
    decision at a time (FIFO), so a slow decision can delay the next reading.
    Returns the end-to-end latency (reading arrival -> decision ready) per event."""
    free, out = 0.0, []
    for ev in events:
        start = max(ev.arrival + ev.edge_tx, free)
        fin = start + edge_compute(ev)
        free = fin
        out.append(fin - ev.arrival)
    return out


def _leg(median, z, u_sp, u_par, c):
    body = median * math.exp(NET_SIGMA * z) * (1.0 + NET_GROW * c)
    spike = 0.0
    if u_sp < SPIKE_P0 + SPIKE_P1 * c:          # congestion spike (heavy-tailed)
        xm = SPIKE_XM0 * (1.0 + c)
        spike = min(SPIKE_CAP, xm * (1.0 - u_par) ** (-1.0 / SPIKE_ALPHA))
    return body + spike


def cloud_latency(ev: Event, congestion: float) -> float:
    """CLOUD end-to-end latency = upload leg + remote compute + download leg.
    Both network legs grow with congestion and occasionally spike (Pareto tail)."""
    up = _leg(UP_MEDIAN, ev.z_up, ev.u_sp_up, ev.u_par_up, congestion)
    dn = _leg(DOWN_MEDIAN, ev.z_dn, ev.u_sp_dn, ev.u_par_dn, congestion)
    mean, sd = CLOUD_HARD if ev.hard else CLOUD_EASY
    comp = max(1.0, mean + sd * ev.z_comp)
    return up + comp + dn


def simulate_cloud(events, congestion):
    # The data centre serves many readings in parallel: no queue.
    return [cloud_latency(ev, congestion) for ev in events]


def simulate_hybrid(events, congestion, triage_ms=TRIAGE_MS, acc=TRIAGE_ACC):
    """HYBRID: the device first runs a quick triage (2 ms). Decisions classified EASY
    stay on the edge processor; decisions classified HARD go to the cloud.
    The triage is right 95% of the time."""
    free, out = 0.0, []
    for ev in events:
        flagged_hard = ev.hard if ev.u_triage < acc else (not ev.hard)
        start = max(ev.arrival + ev.edge_tx, free)
        t_done = start + triage_ms
        if flagged_hard:
            free = t_done
            fin = t_done + cloud_latency(ev, congestion)
        else:
            fin = t_done + edge_compute(ev)
            free = fin
        out.append(fin - ev.arrival)
    return out


# ----------------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------------
def percentile(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    pos = (len(sorted_vals) - 1) * q / 100.0
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def summarise(lat, events=None):
    s = sorted(lat)
    n = len(lat)
    ok = sum(x <= DEADLINE for x in lat)
    p = ok / n
    out = {
        "mean": statistics.mean(lat), "p95": percentile(s, 95), "p99": percentile(s, 99),
        "worst": s[-1], "compliance": 100.0 * p, "ci": 196.0 * math.sqrt(p * (1 - p) / n),
    }
    if events is not None:
        for lab, flag in (("easy", False), ("hard", True)):
            sub = [x for x, e in zip(lat, events) if e.hard == flag]
            out[f"compl_{lab}"] = 100.0 * sum(x <= DEADLINE for x in sub) / len(sub)
    return out


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


def crossing(xs, ys, level):
    """First x where the curve ys(xs) drops below `level` (linear interpolation)."""
    for i in range(1, len(xs)):
        if ys[i - 1] >= level > ys[i]:
            return xs[i - 1] + (xs[i] - xs[i - 1]) * (ys[i - 1] - level) / (ys[i - 1] - ys[i])
    return None


# ----------------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------------
def fig_distributions(lat_edge, lat_cloud, lat_hyb, sums):
    """Figure 1: overlaid latency distributions with the deadline marked."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    bins = [i * 2.5 for i in range(0, 101)]       # 0-250 ms
    for lat, col, lab in ((lat_edge, C_EDGE, "edge"), (lat_cloud, C_CLOUD, "cloud (congestion 0.2)")):
        ax1.hist([min(x, 249.9) for x in lat], bins=bins, histtype="stepfilled", alpha=0.45, color=col,
                 label=lab, density=True, lw=0)
        ax1.hist([min(x, 249.9) for x in lat], bins=bins, histtype="step", color=col, density=True, lw=1.2)
    ax1.axvline(DEADLINE, color=C_REF, ls="--", lw=1.2)
    ax1.text(DEADLINE + 2, ax1.get_ylim()[1] * 0.93, "deadline\n100 ms", fontsize=8, color=C_REF, va="top")
    ax1.set_xlabel("end-to-end latency (ms)   [values above 250 ms are piled into the last bin]")
    ax1.set_ylabel("share of decisions per ms")
    ax1.set_title("Latency distributions", loc="left", fontsize=10, fontweight="bold")
    ax1.legend(loc="upper right", fontsize=8)

    for lat, col, lab, key in ((lat_edge, C_EDGE, "edge", "edge"), (lat_cloud, C_CLOUD, "cloud", "cloud"),
                               (lat_hyb, C_HYB, "hybrid", "hybrid")):
        s = sorted(lat)
        n = len(s)
        step = max(1, n // 2000)
        ax2.plot(s[::step], [100.0 * (i + 1) / n for i in range(0, n, step)], color=col, lw=1.6,
                 label=f"{lab}: {sums[key]['compliance']:.1f}% on time")
    ax2.axvline(DEADLINE, color=C_REF, ls="--", lw=1.2)
    ax2.set_xscale("log")
    ax2.set_xlim(8, 2500)
    ax2.set_ylim(60, 100.5)
    ax2.set_xlabel("end-to-end latency (ms, log scale)")
    ax2.set_ylabel("share of decisions finished by this time (%)")
    ax2.set_title("Empirical CDF (the tail is visible)", loc="left", fontsize=10, fontweight="bold")
    ax2.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig1_latency_distributions.png"))
    plt.close(fig)


def fig_sweep(levels, cloud_c, hyb_c, edge_c, x_edge, x99, x95):
    """Figure 2: deadline compliance versus congestion."""
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    ax.plot(levels, cloud_c, color=C_CLOUD, lw=2, marker="o", ms=3.5, label="cloud")
    ax.plot(levels, hyb_c, color=C_HYB, lw=2, marker="s", ms=3.5, label="hybrid")
    ax.axhline(edge_c, color=C_EDGE, lw=2, label=f"edge ({edge_c:.1f}%, does not depend on congestion)")
    ax.axhline(99.0, color=C_REF, ls=":", lw=1)
    ax.text(1.0, 99.2, "99% target", ha="right", fontsize=8, color=C_REF)
    if x_edge is not None:
        ax.axvline(x_edge, color=C_REF, ls="--", lw=0.9)
        ax.text(x_edge + 0.01, 62.5, f"cloud falls below edge\nat congestion {x_edge:.2f}", fontsize=8, color=C_REF)
    ax.set_xlabel("cloud congestion level (0 = calm network, 1 = heavily congested)")
    ax.set_ylabel("decisions meeting the 100 ms deadline (%)")
    ax.set_ylim(60, 101)
    ax.set_xlim(0, 1)
    ax.set_title("Deadline compliance versus congestion", loc="left", fontsize=10, fontweight="bold")
    ax.legend(loc="lower left", fontsize=8, bbox_to_anchor=(0.0, 0.12))
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig2_compliance_vs_congestion.png"))
    plt.close(fig)


def fig_percentiles(levels, cloud_stats, hyb_stats, edge_stats):
    """Extra figure: average versus tail latency (the URLLC point)."""
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    ax.plot(levels, [s["mean"] for s in cloud_stats], color=C_CLOUD, lw=1.6, ls="-", label="cloud: mean")
    ax.plot(levels, [s["p95"] for s in cloud_stats], color=C_CLOUD, lw=1.6, ls="--", label="cloud: 95th percentile")
    ax.plot(levels, [s["p99"] for s in cloud_stats], color=C_CLOUD, lw=1.6, ls=":", label="cloud: 99th percentile")
    ax.axhline(edge_stats["mean"], color=C_EDGE, lw=1.6, ls="-", label="edge: mean")
    ax.axhline(edge_stats["p99"], color=C_EDGE, lw=1.6, ls=":", label="edge: 99th percentile")
    ax.axhline(DEADLINE, color=C_REF, lw=1.2, ls="--")
    ax.text(0.0, DEADLINE + 3, "deadline 100 ms", fontsize=8, color=C_REF)
    ax.set_yscale("log")
    ax.set_xlabel("cloud congestion level")
    ax.set_ylabel("end-to-end latency (ms, log scale)")
    ax.set_title("A low average hides a long tail", loc="left", fontsize=10, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8, bbox_to_anchor=(0.0, 0.93), ncol=2)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "extra_fig3_mean_vs_tail_latency.png"))
    plt.close(fig)


# ----------------------------------------------------------------------------
def main():
    events = make_events()
    print("Mini Project 4.3 - edge versus cloud latency")
    print(f"{len(events)} decisions, one every {EVENT_PERIOD:.0f} ms, deadline {DEADLINE:.0f} ms, "
          f"{P_HARD:.0%} hard decisions\n")

    lat_edge = simulate_edge(events)
    lat_cloud = simulate_cloud(events, BASELINE_CONGESTION)
    lat_hyb = simulate_hybrid(events, BASELINE_CONGESTION)
    sums = {"edge": summarise(lat_edge, events), "cloud": summarise(lat_cloud, events),
            "hybrid": summarise(lat_hyb, events)}

    # ---- Results table at the baseline congestion ---------------------------
    rows = []
    for key, lab in (("edge", "edge"), ("cloud", f"cloud (congestion {BASELINE_CONGESTION})"),
                     ("hybrid", f"hybrid (congestion {BASELINE_CONGESTION})")):
        s = sums[key]
        rows.append([lab, f"{s['mean']:.1f}", f"{s['p95']:.1f}", f"{s['p99']:.1f}", f"{s['worst']:.0f}",
                     f"{s['compliance']:.2f} +/- {s['ci']:.2f}", f"{s['compl_easy']:.2f}", f"{s['compl_hard']:.2f}"])
    write_table("table1_baseline_results",
                ["architecture", "mean (ms)", "95th pct (ms)", "99th pct (ms)", "worst case (ms)",
                 "deadline met (%) +/- 95% CI", "easy decisions met (%)", "hard decisions met (%)"], rows,
                f"{len(events)} decisions, deadline {DEADLINE:.0f} ms. Cloud and hybrid are shown at the baseline "
                f"congestion level {BASELINE_CONGESTION}. Worst case is capped by the 2 s network time-out.")

    # ---- Congestion sweep ---------------------------------------------------
    levels = [round(0.05 * i, 2) for i in range(21)]
    cloud_stats = [summarise(simulate_cloud(events, c)) for c in levels]
    hyb_stats = [summarise(simulate_hybrid(events, c)) for c in levels]
    srows = []
    for c, a, b in zip(levels, cloud_stats, hyb_stats):
        srows.append([f"{c:.2f}", f"{a['mean']:.1f}", f"{a['p95']:.1f}", f"{a['p99']:.1f}", f"{a['compliance']:.2f}",
                      f"{b['p99']:.1f}", f"{b['compliance']:.2f}", f"{sums['edge']['compliance']:.2f}"])
    write_table("table2_congestion_sweep",
                ["congestion", "cloud mean (ms)", "cloud 95th (ms)", "cloud 99th (ms)", "cloud met (%)",
                 "hybrid 99th (ms)", "hybrid met (%)", "edge met (%) [constant]"], srows,
                "Same 20000 readings at every congestion level.")

    # ---- Where does the cloud stop being compliant? ---------------------------
    cc = [s["compliance"] for s in cloud_stats]
    hc = [s["compliance"] for s in hyb_stats]
    edge_c = sums["edge"]["compliance"]
    x_edge = crossing(levels, cc, edge_c)
    x99 = crossing(levels, cc, 99.0)
    x95 = crossing(levels, cc, 95.0)
    hx99 = crossing(levels, hc, 99.0)
    hx_edge = crossing(levels, hc, edge_c)

    def fmt(x):
        return "never (in 0-1)" if x is None else f"{x:.2f}"
    write_table("table3_thresholds",
                ["question", "congestion level"],
                [["cloud meets 99% of deadlines until congestion reaches", fmt(x99)],
                 ["cloud meets 95% of deadlines until congestion reaches", fmt(x95)],
                 ["cloud becomes worse than pure edge at congestion", fmt(x_edge)],
                 ["hybrid meets 99% of deadlines until congestion reaches", fmt(hx99)],
                 ["hybrid becomes worse than pure edge at congestion", fmt(hx_edge)]],
                "Linear interpolation between the sweep points of table 2.")

    # ---- Hybrid triage accuracy sensitivity -----------------------------------
    trows = []
    for acc in (1.0, 0.95, 0.90, 0.80):
        for c in (BASELINE_CONGESTION, 0.6):
            s = summarise(simulate_hybrid(events, c, acc=acc))
            trows.append([f"{acc:.2f}", f"{c:.2f}", f"{s['p99']:.1f}", f"{s['compliance']:.2f}"])
    write_table("table4_hybrid_triage_sensitivity", ["triage accuracy", "congestion", "hybrid 99th (ms)",
                "hybrid met (%)"], trows, "How much the hybrid policy depends on a good triage.")

    # ---- Figures ----------------------------------------------------------------
    fig_distributions(lat_edge, lat_cloud, lat_hyb, sums)
    fig_sweep(levels, cc, hc, edge_c, x_edge, x99, x95)
    fig_percentiles(levels, cloud_stats, hyb_stats, sums["edge"])

    print("Baseline results (congestion 0.2):")
    with open(os.path.join(RES_DIR, "table1_baseline_results.md")) as fh:
        print(fh.read())
    with open(os.path.join(RES_DIR, "table3_thresholds.md")) as fh:
        print(fh.read())
    print("Tables written to results/, figures to figures/.")


if __name__ == "__main__":
    main()
