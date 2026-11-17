Average over 30 runs per configuration (T_nominal = 50 ms, 400 cycles, overrun computation time 60-150 ms). Delay vs ideal = actuation time in the realistic loop minus actuation time in the ideal loop, for the same true threshold crossing. Latency after true crossing = actuation time minus the exact moment the true signal crossed the threshold (never negative).

| configuration | mean interval (ms) | std interval (ms) | max overrun (ms) | % cycles > T | % overrun cycles | % cycles > 1.5T | mean delay vs ideal (ms) | mean abs delay vs ideal (ms) | max abs delay vs ideal (ms) | mean latency after true crossing (ms) | max latency after true crossing (ms) | worst-run max latency (ms) | crossings >=1 cycle late | crossings missed | final schedule lag (ms) | P-ctrl error (% of ideal RMS) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline  (J=0, p=0) | 50.00 | 0.00 | 0.00 | 0.0 | 0.0 | 0.0 | -0.07 | 0.98 | 1.85 | 34.25 | 55.64 | 57.70 | 0.00 | 0.00 | 0.00 | 2.13 |
| jitter 10% of T | 50.00 | 4.06 | 0.00 | 50.1 | 0.0 | 0.0 | -4.43 | 6.86 | 37.97 | 29.89 | 52.70 | 61.07 | 0.00 | 0.00 | 0.00 | 3.47 |
| jitter 30% of T | 49.99 | 12.18 | 0.00 | 50.1 | 0.0 | 1.3 | -2.43 | 12.03 | 40.88 | 31.89 | 60.17 | 81.07 | 0.17 | 0.00 | 0.00 | 5.85 |
| jitter 50% of T | 50.00 | 20.27 | 0.00 | 50.1 | 0.0 | 12.6 | 0.45 | 18.30 | 46.85 | 34.76 | 71.78 | 96.18 | 0.40 | 0.00 | 4.68 | 7.60 |
| overrun p = 2% | 51.10 | 8.17 | 86.02 | 2.1 | 2.1 | 1.7 | -0.36 | 15.74 | 39.76 | 33.96 | 63.20 | 120.70 | 0.13 | 0.00 | 440.61 | 7.63 |
| overrun p = 5% | 52.82 | 13.29 | 95.43 | 5.2 | 5.2 | 4.3 | 4.79 | 22.37 | 77.03 | 39.10 | 108.88 | 180.33 | 0.80 | 0.00 | 1125.90 | 10.07 |
| overrun p = 10% | 55.54 | 18.18 | 97.88 | 10.3 | 10.3 | 8.5 | 13.31 | 27.91 | 94.02 | 47.63 | 119.74 | 277.82 | 1.53 | 0.00 | 2212.24 | 13.00 |
| both: J=30% T, p=5% | 52.81 | 17.85 | 95.43 | 52.7 | 5.2 | 5.5 | 7.70 | 22.68 | 75.14 | 42.01 | 107.69 | 190.44 | 0.73 | 0.00 | 1123.25 | 10.52 |
| both: J=50% T, p=10% | 55.57 | 26.52 | 97.88 | 55.2 | 10.3 | 20.2 | 17.23 | 33.44 | 104.35 | 51.55 | 135.84 | 238.35 | 1.77 | 0.00 | 2229.09 | 13.82 |
