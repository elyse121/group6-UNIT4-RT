Jitter-only: average |jitter| per cycle = d (J = 2d). Overrun-only: average extra time per cycle = d (p = d / 55 ms). Average over 30 runs.

| avg disturbance (ms/cycle) | hazard | setting | std interval (ms) | % cycles > 1.5T | mean delay vs ideal (ms) | mean abs delay vs ideal (ms) | max abs delay vs ideal (ms) | mean latency after true crossing (ms) | max latency after true crossing (ms) | final schedule lag (ms) | P-ctrl error (% of ideal RMS) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2.5 | jitter only | J=5 ms | 4.06 | 0.0 | -4.43 | 6.86 | 37.97 | 29.89 | 52.70 | 0.00 | 3.47 |
| 2.5 | overrun only | p=4.5% | 12.73 | 3.9 | 5.09 | 21.15 | 72.87 | 39.40 | 102.51 | 1026.45 | 9.81 |
| 5 | jitter only | J=10 ms | 8.12 | 0.0 | -4.44 | 9.09 | 38.48 | 29.88 | 53.47 | 0.00 | 4.80 |
| 5 | overrun only | p=9.1% | 17.36 | 7.7 | 12.23 | 27.81 | 93.70 | 46.55 | 121.24 | 2002.55 | 12.49 |
| 7.5 | jitter only | J=15 ms | 12.18 | 1.3 | -2.43 | 12.03 | 40.88 | 31.89 | 60.17 | 0.00 | 5.85 |
| 7.5 | overrun only | p=13.6% | 20.89 | 11.5 | 12.57 | 24.97 | 81.64 | 46.89 | 112.03 | 3003.53 | 14.94 |
| 10 | jitter only | J=20 ms | 16.24 | 6.6 | -1.94 | 14.60 | 43.12 | 32.38 | 64.40 | 0.00 | 6.75 |
| 10 | overrun only | p=18.2% | 23.90 | 15.5 | 27.25 | 37.38 | 121.93 | 61.57 | 155.05 | 4050.99 | 17.16 |
