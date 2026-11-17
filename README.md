# Real-Time Systems - Unit 4 Lab (Mini Projects 4.1, 4.2, 4.3)

Three Python simulations, each with figures, result tables and a written report (Markdown + PDF).
Everything is reproducible: every random number uses a fixed seed, and every number in the reports
comes from running the code.

## Folder layout

```
RTS_Unit4_Lab/
  README.md
  requirements.txt
  run_all.sh                  runs the three simulations, then rebuilds the reports
  mini_project_4_1/           jitter and overruns in a sensor loop
    rt_sampling_sim.py
    figures/   results/   report/Mini_Project_4_1_Report.(pdf|md)
  mini_project_4_2/           multi-rate environmental monitoring pipeline
    env_monitor_pipeline.py
    figures/   results/   report/Mini_Project_4_2_Report.(pdf|md)
  mini_project_4_3/           edge versus cloud latency
    edge_vs_cloud_sim.py
    figures/   results/   report/Mini_Project_4_3_Report.(pdf|md)
  tools/                      report builder and report text templates
```

## How to run

Needs Python 3.10 or newer.

```
pip install -r requirements.txt
bash run_all.sh                       # everything (about 1 minute)
# or one project at a time:
cd mini_project_4_1 && python3 rt_sampling_sim.py
cd mini_project_4_2 && python3 env_monitor_pipeline.py
cd mini_project_4_3 && python3 edge_vs_cloud_sim.py
```

Each script writes its figures to `figures/` and its tables to `results/` (CSV and Markdown).
`python3 tools/build_reports.py` rebuilds the three reports from the templates and the CSV files.
It also checks that the required report section has the right number of words
(4.1: 200-400, 4.2 and 4.3: 300-500).

## What each project shows

**4.1 Jitter and overruns.** An ideal 20 Hz sampling loop is compared with a loop that has random
timing jitter and occasional processing overruns, driving a threshold controller and a P controller.
Overruns hurt much more than jitter at the same average disturbance (worst-case latency 121 ms against 53 ms
at 5 ms average disturbance per cycle), because jitter averages out and overruns only push one way.
Extra tasks done: jitter-only vs overrun-only, P controller, "cycles over 1.5 T" metric, halved period,
and a comparison of two overrun policies.

**4.2 Multi-rate monitoring.** Four sensors (50, 100, 240, 500 ms periods) share one non-preemptive gateway.
Fixed priority, earliest-deadline-first and round-robin are compared with 3 and 4 streams. Every sample is
classified on-time / late / missed, and alerts log both the true crossing time and the detection time.
Adding the fast sensor takes the gateway from 26% to 47% busy, but on-time temperature samples drop from
94% to 77%: the long read times matter more than the average load. FP and EDF are almost identical here.

**4.3 Edge versus cloud.** 20,000 decisions with a 100 ms deadline on three architectures. Cloud is best for
heavy decisions on a calm network, but has a long tail and falls below pure edge at congestion 0.25.
A hybrid (triage on the device, only hard decisions to the cloud) meets 98.7% of deadlines at baseline congestion.

## Assumptions to know about

All signal shapes, timing distributions and network parameters are modelling assumptions, not measurements of
real hardware. They are listed at the top of each script and in the "Limits of the model" section of each report.
The reports' cover pages leave the student name and registration number blank.
