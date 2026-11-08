iPhone 13 landscape in Chromium, CPU 4x slower; turning a message into a state (decode + delta.js), median of 15 rounds over 900 recorded messages each:

| scenario | JSON.parse | binary decode | per second of play (30 messages), JSON → binary |
|---|---|---|---|
| classic 2p ffa | 6.9 µs | 7.0 µs | 0.21 → 0.21 ms |
| classic 4p ffa | 13.7 µs | 13.2 µs | 0.41 → 0.40 ms |
| platform 4p knockouts +power-ups | 8.4 µs | 9.9 µs | 0.25 → 0.30 ms |
| ramps 6p crown +power-ups | 9.2 µs | 8.4 µs | 0.28 → 0.25 ms |
| grand 8p ffa +power-ups | 10.9 µs | 8.9 µs | 0.33 → 0.27 ms |
| decks 10p lives +power-ups | 12.2 µs | 9.2 µs | 0.37 → 0.28 ms |
