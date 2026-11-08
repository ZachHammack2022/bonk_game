
A real server on one core, browsers on others; 5 runs of 15 s each, variants in turn:

| load | variant | server CPU (median, 95% interval) | vs today | tick p99 | wire per player | states/s (slowest browser) | rebuilt OK |
|---|---|---|---|---|---|---|---|
| 40 rooms of 4 (classic) | json+deflate | 78.4% (77.1–82.2) | +0.0 pts (+0.0 to +0.0) | 0.63 ms | 10.2 kbit/s | 30.0 | 108476 states, 0 failed |
| 40 rooms of 4 (classic) | json | 68.6% (67.1–69.8) | -9.0 pts (-15.1 to -8.5) | 0.62 ms | 30.4 kbit/s | 30.0 | 108455 states, 0 failed |
| 40 rooms of 4 (classic) | bin | 71.2% (67.6–72.0) | -9.0 pts (-10.2 to -6.6) | 0.73 ms | 12.5 kbit/s | 30.0 | 108467 states, 0 failed |
| 40 rooms of 4 (classic) | bin+deflate | 78.1% (75.0–80.5) | -2.1 pts (-4.4 to +2.2) | 0.61 ms | 7.3 kbit/s | 30.0 | 108501 states, 0 failed |
| 20 rooms of 8 (grand) | json+deflate | 70.8% (64.0–73.8) | +0.0 pts (+0.0 to +0.0) | 1.37 ms | 12.4 kbit/s | 30.0 | 54222 states, 0 failed |
| 20 rooms of 8 (grand) | json | 63.1% (57.0–71.6) | -7.8 pts (-13.4 to -0.9) | 1.47 ms | 38.2 kbit/s | 29.9 | 54173 states, 0 failed |
| 20 rooms of 8 (grand) | bin | 59.6% (57.8–63.2) | -10.6 pts (-11.8 to -4.5) | 1.36 ms | 11.9 kbit/s | 30.0 | 54175 states, 0 failed |
| 20 rooms of 8 (grand) | bin+deflate | 66.7% (65.1–68.0) | -4.5 pts (-7.1 to +1.0) | 1.38 ms | 7.9 kbit/s | 30.0 | 54226 states, 0 failed |
