Average over 30 independent random workloads. Every rule sees the same workload in each run.

| load | rule | stream | % on time | % late | % missed | mean period overrun (ms) | max period overrun (ms, mean of runs) | alerts missed / true events | mean alert latency (ms) | max alert latency (ms, mean of runs) |
|---|---|---|---|---|---|---|---|---|---|---|
| 3 streams | FP | Temperature | 94.0 | 5.5 | 0.5 | 3.0 | 122.5 | 0.00 / 3 | 71.4 | 112.4 |
| 3 streams | FP | Humidity | 94.1 | 5.9 | 0.1 | 7.6 | 194.6 | 0.00 / 2 | 181.5 | 234.6 |
| 3 streams | FP | Air quality | 94.1 | 5.9 | 0.0 | 13.1 | 239.0 | 0.03 / 5 | 222.6 | 520.4 |
| 3 streams | EDF | Temperature | 94.0 | 5.5 | 0.5 | 3.0 | 123.9 | 0.00 / 3 | 71.4 | 112.4 |
| 3 streams | EDF | Humidity | 94.1 | 5.9 | 0.1 | 7.6 | 193.0 | 0.00 / 2 | 181.5 | 234.6 |
| 3 streams | EDF | Air quality | 94.1 | 5.9 | 0.0 | 13.1 | 238.3 | 0.03 / 5 | 222.6 | 520.4 |
| 3 streams | RR | Temperature | 79.5 | 18.5 | 2.0 | 9.3 | 185.0 | 0.00 / 3 | 78.3 | 131.8 |
| 3 streams | RR | Humidity | 95.3 | 4.7 | 0.0 | 5.1 | 141.0 | 0.00 / 2 | 175.8 | 223.9 |
| 3 streams | RR | Air quality | 98.9 | 1.1 | 0.0 | 4.2 | 114.6 | 0.00 / 5 | 209.0 | 513.8 |
| 4 streams | FP | Temperature | 76.7 | 16.5 | 6.8 | 15.2 | 282.4 | 0.00 / 3 | 52.2 | 90.2 |
| 4 streams | FP | Humidity | 82.1 | 17.0 | 1.0 | 20.2 | 304.5 | 0.00 / 2 | 192.2 | 248.4 |
| 4 streams | FP | Air quality | 85.1 | 14.9 | 0.1 | 28.6 | 355.0 | 0.00 / 5 | 167.7 | 331.1 |
| 4 streams | FP | Vibration (fast) | 79.9 | 10.3 | 9.8 | 8.2 | 129.5 | 0.33 / 11 | 29.7 | 106.2 |
| 4 streams | EDF | Temperature | 76.6 | 16.5 | 6.9 | 15.3 | 289.4 | 0.00 / 3 | 52.5 | 90.4 |
| 4 streams | EDF | Humidity | 81.9 | 17.4 | 0.6 | 19.9 | 292.6 | 0.00 / 2 | 191.9 | 248.0 |
| 4 streams | EDF | Air quality | 85.1 | 14.8 | 0.1 | 28.5 | 346.5 | 0.00 / 5 | 167.7 | 331.2 |
| 4 streams | EDF | Vibration (fast) | 79.8 | 10.3 | 9.8 | 8.2 | 134.3 | 0.33 / 11 | 29.7 | 106.2 |
| 4 streams | RR | Temperature | 79.3 | 16.9 | 3.8 | 11.9 | 223.8 | 0.00 / 3 | 68.5 | 109.7 |
| 4 streams | RR | Humidity | 85.5 | 14.4 | 0.1 | 14.3 | 190.9 | 0.00 / 2 | 181.8 | 231.0 |
| 4 streams | RR | Air quality | 93.1 | 6.9 | 0.0 | 15.5 | 194.8 | 0.03 / 5 | 212.4 | 484.7 |
| 4 streams | RR | Vibration (fast) | 65.0 | 18.7 | 16.3 | 15.9 | 289.3 | 0.67 / 11 | 30.3 | 102.7 |
