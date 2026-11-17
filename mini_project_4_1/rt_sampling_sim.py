#!/usr/bin/env python3
"""
Mini Project 4.1 - Simulating Sampling Jitter and Processing Overruns
in an Embedded Sensing-and-Control Loop
Real-Time Systems, Unit 4 Lab

What this script does
---------------------
1. Simulates a physical signal (a sine wave plus a little continuous noise).
2. Samples it with an IDEAL loop (perfect timing) and a REALISTIC loop that has
   - sampling jitter    (each sample is taken a little early or late), and
   - processing overruns (the computation sometimes takes longer than the period).
3. Runs a threshold controller (and, as an extra task, a proportional controller)
   on both loops and measures how much later / how differently the realistic
   loop acts.
4. Produces figures, tables (CSV + Markdown) for the whole lab task list.

Run:   python3 rt_sampling_sim.py
Needs: Python 3.10+, matplotlib (standard library for everything else).
All results are reproducible: every random draw uses a fixed seed.
"""

import bisect
import csv
import math
import os
import random
import statistics
from dataclasses import dataclass, replace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(HERE, "figures")
RES_DIR = os.path.join(HERE, "results")
os.makedirs(FIG_DIR, exist_ok=True)
os.makedirs(RES_DIR, exist_ok=True)

# Colour-blind-safe colours (Okabe-Ito), used the same way in every figure
C_IDEAL = "#0072B2"   # blue   : ideal loop
C_REAL = "#D55E00"    # orange : jittered / overrunning loop
C_OVER = "#CC79A7"    # purple : overrun cycles
C_SIG = "#555555"     # grey   : true signal
C_GOOD = "#009E73"    # green  : third series when needed

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "legend.frameon": False,
})

# ----------------------------------------------------------------------------
# 1. The physical process
# ----------------------------------------------------------------------------
SIG_AMP = 1.0        # amplitude of the sine wave
SIG_PERIOD = 2.0937    # seconds per full sine cycle (not a multiple of T, so crossings hit different sampling phases)
THRESH = 0.5         # the controller fires when the signal rises through this value


def true_signal(t: float) -> float:
    """The continuous analogue quantity a real sensor observes.

    A sine wave plus a small *continuous* noise term. The noise is built from two
    small fast sine waves instead of random numbers, so true_signal(t) is a proper
    function of time: sampling the same instant twice gives the same value. The
    noise is small enough that the signal crosses the threshold only once per
    rising edge (so "which crossing is which" is never ambiguous).
    """
    base = SIG_AMP * math.sin(2.0 * math.pi * t / SIG_PERIOD)
    noise = (0.010 * math.sin(2.0 * math.pi * 3.1 * t + 0.7)
             + 0.005 * math.sin(2.0 * math.pi * 7.7 * t + 2.1))
    return base + noise


_TRUE_X = None


def true_cross_times(t_max: float = 60.0, dt: float = 0.001):
    """Exact times (found by bisection) where the true signal rises through THRESH."""
    global _TRUE_X
    if _TRUE_X is None:
        xs, prev_t = [], 0.0
        prev_v = true_signal(0.0) - THRESH
        n = int(t_max / dt)
        for i in range(1, n + 1):
            t = i * dt
            v = true_signal(t) - THRESH
            if prev_v < 0.0 <= v:
                lo, hi = prev_t, t
                for _ in range(50):
                    mid = 0.5 * (lo + hi)
                    if true_signal(mid) - THRESH < 0.0:
                        lo = mid
                    else:
                        hi = mid
                xs.append(0.5 * (lo + hi))
            prev_t, prev_v = t, v
        _TRUE_X = xs
    return _TRUE_X


# ----------------------------------------------------------------------------
# 2. The sampling loop (ideal and realistic)
# ----------------------------------------------------------------------------
@dataclass
class Config:
    T: float = 0.05                  # nominal sampling period (s)  -> 20 Hz
    duration: float = 20.0           # scheduled run length (s)
    jitter_abs: float = 0.0          # J: jitter drawn from uniform(-J, +J) seconds
    p_overrun: float = 0.0           # probability that a cycle's computation overruns
    normal_c: tuple = (0.004, 0.008)  # normal computation time range (s)
    overrun_c: tuple = (0.060, 0.150)  # overrun computation time range (s) = 1.2T..3T
    policy: str = "rebase"           # "rebase" or "catch_up" (see simulate())
    seed: int = 1


@dataclass
class Run:
    T: float
    s: list        # actual sample times
    y: list        # sampled values
    c: list        # computation time of each cycle
    f: list        # time each cycle finishes = when the actuation is issued
    jitter: list   # jitter applied to each cycle
    overrun: list  # True where c_k > T
    drift: list    # accumulated schedule drift (seconds) after each cycle


def simulate(cfg: Config, ideal: bool = False) -> Run:
    """Run one simulated loop.

    Model of one cycle k (a single-threaded loop, like a PLC scan):
      planned_k = k*T + drift + jitter_k      (when the sample is *meant* to happen)
      The loop cannot sample while the previous cycle is still computing, so
      sample_k = max(planned_k, finish_{k-1}).
      finish_k = sample_k + c_k               (the actuation is issued here)

    If the previous computation ran past planned_k (an overrun) the next cycle is
    delayed. What happens to the schedule afterwards depends on cfg.policy:
      "rebase"   : the schedule is moved later for good (drift grows). This is the
                   PLC scan-cycle model: the next scan starts when the last one ends.
      "catch_up" : the schedule stays where it was; late cycles run back-to-back
                   until the loop is back on its original grid.

    ideal=True gives the zero-jitter, zero-overrun baseline: sample_k = k*T and
    a fixed computation time equal to the mean normal computation time.
    """
    T = cfg.T
    n = int(round(cfg.duration / T))
    # Separate random streams so changing J never changes the overrun pattern
    # (and vice versa). This makes sweeps comparable ("common random numbers").
    r_jit = random.Random(cfg.seed * 1000 + 1)
    r_cmp = random.Random(cfg.seed * 1000 + 2)
    c_ideal = 0.5 * (cfg.normal_c[0] + cfg.normal_c[1])

    s, c, f, jit, ovr, dr = [], [], [], [], [], []
    clock, drift = 0.0, 0.0
    for k in range(n):
        u_j = r_jit.uniform(-1.0, 1.0)
        u_o = r_cmp.random()
        c_norm = r_cmp.uniform(*cfg.normal_c)
        c_over = r_cmp.uniform(*cfg.overrun_c)
        if ideal:
            sk, ck, j = k * T, c_ideal, 0.0
        else:
            j = u_j * cfg.jitter_abs
            ck = c_over if u_o < cfg.p_overrun else c_norm
            planned = k * T + drift + j
            if k > 0 and planned < clock:
                if cfg.policy == "rebase":
                    drift += clock - planned
                sk = clock
            else:
                sk = max(planned, 0.0)
        s.append(sk)
        c.append(ck)
        f.append(sk + ck)
        jit.append(j)
        ovr.append(ck > T)
        dr.append(drift)
        clock = sk + ck
    y = [true_signal(t) for t in s]
    return Run(T, s, y, c, f, jit, ovr, dr)


# ----------------------------------------------------------------------------
# 3. Controllers and metrics
# ----------------------------------------------------------------------------
def detect(run: Run):
    """Threshold controller: fire when a sample crosses THRESH from below.
    The command is issued when the cycle finishes (after its computation)."""
    return [(k, run.s[k], run.f[k]) for k in range(1, len(run.y))
            if run.y[k - 1] < THRESH <= run.y[k]]


def assign_crossings(run: Run):
    """Map each detection to the true crossing it belongs to.
    Because the true signal crosses once between the previous and the current
    sample, matching is by *identity of the true crossing*, not by list position.
    Returns {crossing_index: (sample_time, actuation_time)}."""
    tx = true_cross_times()
    out = {}
    for k, sk, fk in detect(run):
        prev = run.s[k - 1]
        i = bisect.bisect_right(tx, prev)
        if i < len(tx) and tx[i] <= sk:
            out[i] = (sk, fk)
    return out


def timing_stats(run: Run) -> dict:
    T = run.T
    iv = [b - a for a, b in zip(run.s, run.s[1:])]
    eps = 1e-9
    return {
        "mean_iv": statistics.mean(iv),
        "std_iv": statistics.stdev(iv),
        "max_overrun": max(0.0, max(run.c) - T),
        "pct_gt_T": 100.0 * sum(x > T + eps for x in iv) / len(iv),
        "pct_overrun": 100.0 * sum(run.overrun) / len(run.overrun),
        "pct_gt_1p5T": 100.0 * sum(x > 1.5 * T + eps for x in iv) / len(iv),
        "final_lag": run.drift[-1],
        "rel_jitter": statistics.stdev(iv) / statistics.mean(iv),
    }


def control_metrics(ideal: Run, run: Run, ref=None) -> dict:
    """Actuation delay of the realistic loop relative to the ideal loop,
    crossing by crossing (lab step 9)."""
    tx = true_cross_times()
    ref = ref if ref is not None else assign_crossings(ideal)
    got = assign_crossings(run)
    delays, lat, missed = [], [], 0
    for n_, (_, f_ideal) in ref.items():
        if n_ in got:
            delays.append(got[n_][1] - f_ideal)
            lat.append(got[n_][1] - tx[n_])
        else:
            missed += 1
    T = run.T
    return {
        "n_cross": len(ref),
        "mean_delay": statistics.mean(delays),
        "mean_abs_delay": statistics.mean(abs(d) for d in delays),
        "max_delay": max(delays),
        "max_abs_delay": max(abs(d) for d in delays),
        "min_delay": min(delays),
        "n_late_cycle": sum(d >= T for d in delays),
        "n_missed": missed,
        "mean_latency_true": statistics.mean(lat),
        "max_latency_true": max(lat),
    }


KP = 2.0         # proportional gain of the P-type controller (extra task 2)
SETPOINT = 0.0


def p_trace(run: Run, grid):
    """Held (zero-order-hold) command of the P controller u = Kp*(r - y_k),
    applied at the end of cycle k and held until the next actuation."""
    u, idx, n = [], -1, len(run.f)
    for t in grid:
        while idx + 1 < n and run.f[idx + 1] <= t:
            idx += 1
        u.append(0.0 if idx < 0 else KP * (SETPOINT - run.y[idx]))
    return u


def p_metrics(u_ideal, run: Run, grid) -> dict:
    u = p_trace(run, grid)
    d = [a - b for a, b in zip(u, u_ideal)]
    rms = math.sqrt(sum(x * x for x in d) / len(d))
    rms_ref = math.sqrt(sum(x * x for x in u_ideal) / len(u_ideal))
    return {"p_rms": rms, "p_max": max(abs(x) for x in d), "p_norm_pct": 100.0 * rms / rms_ref}


# Cache of ideal-run quantities (they do not depend on the seed)
_IDEAL = {}


def ideal_bundle(cfg: Config):
    key = (cfg.T, cfg.duration, cfg.normal_c)
    if key not in _IDEAL:
        run = simulate(cfg, ideal=True)
        grid = [i * 0.001 for i in range(int(cfg.duration / 0.001) + 1)]
        _IDEAL[key] = (run, assign_crossings(run), grid, p_trace(run, grid))
    return _IDEAL[key]


SEEDS = list(range(1, 31))   # 30 independent random runs per configuration


def evaluate(cfg: Config, seeds=SEEDS) -> dict:
    ideal, ref, grid, u_ideal = ideal_bundle(cfg)
    rows = []
    for sd in seeds:
        run = simulate(replace(cfg, seed=sd))
        rows.append({**timing_stats(run), **control_metrics(ideal, run, ref),
                     **p_metrics(u_ideal, run, grid)})
    agg = {k: statistics.mean(r[k] for r in rows) for k in rows[0]}
    agg["max_delay_worst"] = max(r["max_delay"] for r in rows)
    agg["max_latency_worst"] = max(r["max_latency_true"] for r in rows)
    return agg


# ----------------------------------------------------------------------------
# 4. Tables
# ----------------------------------------------------------------------------
def write_table(name: str, header: list, rows: list, note: str = ""):
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


def ms(x):   # seconds -> milliseconds string
    return f"{x * 1000:.2f}"


def f1(x):
    return f"{x:.1f}"


# ----------------------------------------------------------------------------
# 5. Figures
# ----------------------------------------------------------------------------
def figure1(cfg: Config, tag: str, title: str):
    """Figure 1: (top) true signal with ideal and jittered sample points,
    (bottom) per-cycle inter-sample interval minus T_nominal."""
    ideal = simulate(cfg, ideal=True)
    run = simulate(cfg)
    T = cfg.T
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.5, 6.2), gridspec_kw={"height_ratios": [1.15, 1]})
    # top: first 6 s (3 signal periods) so individual samples can be seen
    tmax = 6.0
    tt = [i * 0.002 for i in range(int(tmax / 0.002) + 1)]
    ax1.plot(tt, [true_signal(t) for t in tt], color=C_SIG, lw=1.2, label="true signal")
    ax1.axhline(THRESH, color=C_SIG, ls=":", lw=0.9)
    ax1.text(tmax, THRESH + 0.03, "threshold", ha="right", fontsize=8, color=C_SIG)
    ki = [k for k, t in enumerate(ideal.s) if t <= tmax]
    kj = [k for k, t in enumerate(run.s) if t <= tmax]
    ax1.plot([ideal.s[k] for k in ki], [ideal.y[k] for k in ki], "o", ms=4.5, mfc="none",
             mec=C_IDEAL, mew=1.0, ls="none", label="ideal samples")
    ax1.plot([run.s[k] for k in kj], [run.y[k] for k in kj], "x", ms=4.5, mec=C_REAL,
             mew=1.0, ls="none", label="jittered / overrun samples")
    ax1.set_ylabel("signal value")
    ax1.set_xlabel("time (s)   [zoom: first 6 s of the 20 s run]")
    ax1.set_title(title, loc="left", fontsize=10, fontweight="bold")
    ax1.set_ylim(-1.15, 1.55)
    ax1.legend(loc="upper center", ncol=3, fontsize=8)
    # bottom: full run
    iv = [(b - a - T) * 1000 for a, b in zip(run.s, run.s[1:])]
    ks = list(range(1, len(run.s)))
    ax2.axhline(0, color=C_IDEAL, lw=1.4, label="ideal loop (always 0)")
    ax2.plot(ks, iv, color=C_REAL, lw=0.9, marker=".", ms=3, label="actual interval - T_nominal")
    ov = [k for k in ks if run.overrun[k - 1]]
    if ov:
        ax2.plot(ov, [iv[k - 1] for k in ov], "D", color=C_OVER, ms=4.5, ls="none",
                 label="cycle that overran (c_k > T)")
    ax2.set_xlabel("cycle index k")
    ax2.set_ylabel("interval - T (ms)")
    lo, hi = min(iv + [0]), max(iv + [0])
    ax2.set_ylim(lo - 0.1 * (hi - lo) - 5, hi + 0.45 * (hi - lo) + 5)
    ax2.legend(loc="upper right", fontsize=8, ncol=1)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, f"config_{tag}_fig1_signal_and_jitter.png"))
    plt.close(fig)


def figure2(cfg: Config, tag: str, title: str):
    """Figure 2: ideal vs realistic actuation instants on a shared time axis,
    annotated with mean and maximum actuation delay."""
    ideal = simulate(cfg, ideal=True)
    run = simulate(cfg)
    ref, got = assign_crossings(ideal), assign_crossings(run)
    common = sorted(n for n in ref if n in got)
    t_ideal = [ref[n][1] for n in common]
    t_real = [got[n][1] for n in common]
    d_ms = [(got[n][1] - ref[n][1]) * 1000 for n in common]
    mean_d, max_d = statistics.mean(d_ms), max(abs(x) for x in d_ms)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.5, 5.4), sharex=True,
                                   gridspec_kw={"height_ratios": [1, 1.1]})
    ax1.eventplot([t_ideal, t_real], lineoffsets=[1, 0], linelengths=0.7,
                  linewidths=2.0, colors=[C_IDEAL, C_REAL])
    ax1.set_yticks([0, 1])
    ax1.set_yticklabels(["jittered / overrun\ncontroller", "ideal\ncontroller"])
    ax1.set_ylim(-0.7, 1.7)
    ax1.grid(axis="y", visible=False)
    ax1.set_title(title, loc="left", fontsize=10, fontweight="bold")
    ax2.text(0.99, 0.95, f"mean delay = {mean_d:.2f} ms     max abs delay = {max_d:.2f} ms",
             transform=ax2.transAxes, ha="right", va="top", fontsize=8.5,
             bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#BBBBBB"))
    ax2.axhline(0, color=C_IDEAL, lw=1.2)
    ax2.bar(t_ideal, d_ms, width=0.25, color=C_REAL)
    ax2.set_ylabel("actuation delay (ms)")
    ax2.set_xlabel("time of actuation in the ideal loop (s)")
    ax2.axhline(mean_d, color=C_SIG, ls="--", lw=1)
    ax2.text(t_ideal[0], mean_d, "  mean", va="bottom", fontsize=8, color=C_SIG)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, f"config_{tag}_fig2_actuation_instants.png"))
    plt.close(fig)
    return mean_d, max_d


def figure_lag(cfg: Config):
    """Extra figure: how far behind the original schedule the loop falls,
    for the two overrun policies."""
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for pol, col, lab in (("rebase", C_REAL, "rebase (PLC-style: schedule moves later for good)"),
                          ("catch_up", C_IDEAL, "catch-up (loop runs back-to-back until on schedule)")):
        run = simulate(replace(cfg, policy=pol))
        lag = [(t - k * cfg.T) * 1000 for k, t in enumerate(run.s)]
        ax.plot(range(len(lag)), lag, color=col, lw=1.3, label=lab)
    ax.set_xlabel("cycle index k")
    ax.set_ylabel("lag behind schedule (ms)")
    ax.set_title(f"Schedule lag with overruns (p = {cfg.p_overrun:.0%}, J = 0)", loc="left",
                 fontsize=10, fontweight="bold")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "extra_fig3_schedule_lag_policies.png"))
    plt.close(fig)


def figure_equal(eq_rows):
    """Extra figure: jitter vs overrun at equal average disturbance."""
    d = [r["d"] for r in eq_rows]
    x = list(range(len(d)))
    w = 0.38
    fig, axs = plt.subplots(2, 2, figsize=(9.5, 6.2))
    axes = axs.ravel()
    panels = [("mean_latency_true", "mean latency after true crossing (ms)"),
              ("max_latency_true", "max latency after true crossing (ms)"),
              ("mean_abs_delay", "mean abs delay vs ideal loop (ms)"),
              ("p_norm_pct", "P-controller output error (% of ideal RMS)")]
    for ax, (key, lab) in zip(axes, panels):
        sc = 1.0 if key == "p_norm_pct" else 1000.0
        ax.bar([i - w / 2 for i in x], [r["jit"][key] * sc for r in eq_rows], w,
               color=C_IDEAL, label="jitter only")
        ax.bar([i + w / 2 for i in x], [r["ovr"][key] * sc for r in eq_rows], w,
               color=C_REAL, label="overrun only")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{v:g} ms" for v in d])
        ax.set_xlabel("average disturbance per cycle")
        ax.set_ylabel(lab)
        ax.grid(axis="x", visible=False)
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Equal average disturbance: which hazard hurts the control loop more?",
                 x=0.01, ha="left", fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "extra_fig4_jitter_vs_overrun_equal_disturbance.png"))
    plt.close(fig)


# ----------------------------------------------------------------------------
# 6. Main experiment
# ----------------------------------------------------------------------------
T0 = 0.05
SWEEP = [
    ("baseline  (J=0, p=0)", 0.0, 0.00),
    ("jitter 10% of T", 0.1 * T0, 0.00),
    ("jitter 30% of T", 0.3 * T0, 0.00),
    ("jitter 50% of T", 0.5 * T0, 0.00),
    ("overrun p = 2%", 0.0, 0.02),
    ("overrun p = 5%", 0.0, 0.05),
    ("overrun p = 10%", 0.0, 0.10),
    ("both: J=30% T, p=5%", 0.3 * T0, 0.05),
    ("both: J=50% T, p=10%", 0.5 * T0, 0.10),
]

FIG_CONFIGS = [
    ("A_jitter_only_30pct", 0.3 * T0, 0.00, "Config A - jitter only (J = 30% of T, no overruns)"),
    ("B_overrun_only_5pct", 0.0, 0.05, "Config B - overruns only (p = 5%, no jitter)"),
    ("C_combined_30pct_5pct", 0.3 * T0, 0.05, "Config C - jitter J = 30% of T and overruns p = 5%"),
    ("D_heavy_50pct_10pct", 0.5 * T0, 0.10, "Config D - heavy: J = 50% of T and overruns p = 10%"),
]


def main():
    base = Config()
    print("Mini Project 4.1 - sampling jitter and processing overruns")
    print(f"T_nominal = {base.T*1000:.0f} ms, run = {base.duration:.0f} s, "
          f"{int(base.duration/base.T)} cycles, {len(SEEDS)} seeds per configuration\n")

    # --- sanity check (lab 'Expected Observations' bullet 1) ----------------
    r0 = evaluate(base)
    print(f"Sanity check J=0, p=0: mean |delay| = {r0['mean_abs_delay']*1000:.3f} ms, "
          f"max delay = {r0['max_delay']*1000:.3f} ms (should be ~0-2 ms)\n")

    # --- Figures 1 and 2 for four configurations ----------------------------
    fig_stats = []
    for tag, J, p, title in FIG_CONFIGS:
        cfg = replace(base, jitter_abs=J, p_overrun=p)
        figure1(cfg, tag, title)
        md, xd = figure2(cfg, tag, title)
        fig_stats.append([title.split(" - ")[0], f"J={J*1000:.1f} ms", f"p={p:.0%}", f"{md:.2f}", f"{xd:.2f}"])
    write_table("figure_run_stats", ["config", "jitter bound", "overrun prob.", "mean delay (ms)", "max abs delay (ms)"],
                fig_stats, "Single run (seed 1) used for Figure 2 of each configuration.")

    # --- Main sweep: timing statistics + control-quality metrics ------------
    header = ["configuration", "mean interval (ms)", "std interval (ms)", "max overrun (ms)",
              "% cycles > T", "% overrun cycles", "% cycles > 1.5T",
              "mean delay vs ideal (ms)", "mean abs delay vs ideal (ms)", "max abs delay vs ideal (ms)",
              "mean latency after true crossing (ms)", "max latency after true crossing (ms)",
              "worst-run max latency (ms)", "crossings >=1 cycle late", "crossings missed", "final schedule lag (ms)",
              "P-ctrl error (% of ideal RMS)"]
    rows, sweep = [], {}
    for name, J, p in SWEEP:
        a = evaluate(replace(base, jitter_abs=J, p_overrun=p))
        sweep[name] = a
        rows.append([name, ms(a["mean_iv"]), ms(a["std_iv"]), ms(a["max_overrun"]),
                     f1(a["pct_gt_T"]), f1(a["pct_overrun"]), f1(a["pct_gt_1p5T"]),
                     ms(a["mean_delay"]), ms(a["mean_abs_delay"]), ms(a["max_abs_delay"]),
                     ms(a["mean_latency_true"]), ms(a["max_latency_true"]),
                     ms(a["max_latency_worst"]), f"{a['n_late_cycle']:.2f}", f"{a['n_missed']:.2f}",
                     ms(a["final_lag"]), f"{a['p_norm_pct']:.2f}"])
    write_table("table1_sweep_timing_and_control_quality", header, rows,
                f"Average over {len(SEEDS)} runs per configuration (T_nominal = 50 ms, 400 cycles, "
                "overrun computation time 60-150 ms). Delay vs ideal = actuation time in the realistic loop minus "
                "actuation time in the ideal loop, for the same true threshold crossing. Latency after true "
                "crossing = actuation time minus the exact moment the true signal crossed the threshold "
                "(never negative).")

    # --- Task 1: jitter-only vs overrun-only at equal AVERAGE disturbance ---
    mean_excess = 0.5 * sum(base.overrun_c) - base.T       # average (c - T) of an overrun
    eq_rows, eq_tab = [], []
    for d_ms in (2.5, 5.0, 7.5, 10.0):
        d = d_ms / 1000.0
        J = 2.0 * d                      # mean |jitter| of uniform(-J, J) is J/2 = d
        p = d / mean_excess              # mean extra time per cycle = p * mean_excess = d
        aj = evaluate(replace(base, jitter_abs=J, p_overrun=0.0))
        ao = evaluate(replace(base, jitter_abs=0.0, p_overrun=p))
        eq_rows.append({"d": d_ms, "jit": aj, "ovr": ao})
        for lab, a, extra in (("jitter only", aj, f"J={J*1000:.0f} ms"),
                              ("overrun only", ao, f"p={p:.1%}")):
            eq_tab.append([f"{d_ms:g}", lab, extra, ms(a["std_iv"]), f1(a["pct_gt_1p5T"]),
                           ms(a["mean_delay"]), ms(a["mean_abs_delay"]), ms(a["max_abs_delay"]),
                           ms(a["mean_latency_true"]), ms(a["max_latency_true"]), ms(a["final_lag"]),
                           f"{a['p_norm_pct']:.2f}"])
    write_table("table2_equal_average_disturbance",
                ["avg disturbance (ms/cycle)", "hazard", "setting", "std interval (ms)", "% cycles > 1.5T",
                 "mean delay vs ideal (ms)", "mean abs delay vs ideal (ms)", "max abs delay vs ideal (ms)",
                 "mean latency after true crossing (ms)", "max latency after true crossing (ms)",
                 "final schedule lag (ms)", "P-ctrl error (% of ideal RMS)"],
                eq_tab,
                "Jitter-only: average |jitter| per cycle = d (J = 2d). Overrun-only: average extra time "
                "per cycle = d (p = d / 55 ms). Average over 30 runs.")
    figure_equal(eq_rows)

    # --- Task 3: compliance metric vs raw standard deviation ----------------
    comp = []
    for name, J, p in SWEEP[1:]:
        a = sweep[name]
        comp.append([name, ms(a["std_iv"]), f1(a["pct_gt_1p5T"]), ms(a["mean_latency_true"]),
                     ms(a["max_latency_true"])])
    write_table("table3_compliance_vs_std", ["configuration", "std of interval (ms)", "% cycles > 1.5T",
                "mean latency after true crossing (ms)", "max latency after true crossing (ms)"], comp,
                "Compares the raw jitter standard deviation with the compliance metric (% cycles > 1.5 T).")

    # --- Task 4: halve T_nominal with fixed absolute disturbances -----------
    halve = []
    for T_ in (0.05, 0.025):
        for name, J, p in (("jitter only (J = 15 ms)", 0.015, 0.0), ("overrun only (p = 5%)", 0.0, 0.05),
                           ("both (J = 15 ms, p = 5%)", 0.015, 0.05)):
            a = evaluate(replace(base, T=T_, jitter_abs=J, p_overrun=p))
            halve.append([f"{T_*1000:g}", f"{1/T_:.0f}", name, f"{J / T_ * 100:.0f}", f"{a['rel_jitter']*100:.1f}",
                          f1(a["pct_gt_1p5T"]), f1(a["pct_overrun"]), ms(a["mean_latency_true"]),
                          ms(a["max_latency_true"]), f"{a['p_norm_pct']:.2f}"])
    write_table("table4_halved_period", ["T_nominal (ms)", "rate (Hz)", "hazard (absolute size fixed)",
                "J / T (%)", "std interval / mean interval (%)", "% cycles > 1.5T", "% overrun cycles (c > T)",
                "mean latency after true crossing (ms)", "max latency after true crossing (ms)",
                "P-ctrl error (% of ideal RMS)"], halve,
                "Absolute jitter bound (15 ms) and overrun durations (60-150 ms) are held fixed while the "
                "period is halved from 50 ms to 25 ms. Average over 30 runs.")

    # --- Overrun policy comparison -----------------------------------------
    pol = []
    for p in (0.02, 0.05, 0.10):
        for policy in ("rebase", "catch_up"):
            a = evaluate(replace(base, p_overrun=p, policy=policy))
            pol.append([f"{p:.0%}", policy, ms(a["final_lag"]), ms(a["mean_latency_true"]),
                        ms(a["max_latency_true"]), f"{a['p_norm_pct']:.2f}"])
    write_table("table5_overrun_policy", ["overrun prob.", "policy", "final schedule lag (ms)",
                "mean latency after true crossing (ms)", "max latency after true crossing (ms)",
                "P-ctrl error (% of ideal RMS)"], pol,
                "Rebase = the schedule moves later after an overrun (PLC scan). Catch-up = the original "
                "schedule is kept. Average over 30 runs.")
    figure_lag(replace(base, p_overrun=0.05))

    print("Tables written to results/, figures to figures/.")
    print("\n--- Table 1 (sweep) ---")
    with open(os.path.join(RES_DIR, "table1_sweep_timing_and_control_quality.md")) as fh:
        print(fh.read())


if __name__ == "__main__":
    main()
