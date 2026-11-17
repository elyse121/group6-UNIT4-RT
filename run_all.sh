#!/usr/bin/env bash
# Runs all three simulations, then rebuilds the PDF/Markdown reports.
set -e
cd "$(dirname "$0")"
(cd mini_project_4_1 && python3 rt_sampling_sim.py > /dev/null && echo "4.1 done")
(cd mini_project_4_2 && python3 env_monitor_pipeline.py > /dev/null && echo "4.2 done")
(cd mini_project_4_3 && python3 edge_vs_cloud_sim.py > /dev/null && echo "4.3 done")
python3 tools/build_reports.py
