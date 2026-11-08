
Server CPU to send one tick to everyone in a room (median of 20 rounds, 95% interval), and what the game itself costs per tick:

| scenario | game, bots playing | game, people playing | json+deflate | json | bin | bin+deflate |
|---|---|---|---|---|---|---|
| classic 2p ffa | 217 µs | 109 µs | 17 µs (16–18) | 6 µs (6–7) | 5 µs (5–6) | 15 µs (15–16) |
| classic 4p ffa | 373 µs | 170 µs | 31 µs (31–32) | 8 µs (8–8) | 8 µs (8–8) | 29 µs (29–30) |
| platform 4p knockouts +power-ups | 469 µs | 313 µs | 30 µs (30–31) | 8 µs (8–9) | 8 µs (8–9) | 28 µs (28–29) |
| ramps 6p crown +power-ups | 856 µs | 505 µs | 63 µs (55–71) | 16 µs (13–19) | 11 µs (11–17) | 56 µs (51–66) |
| grand 8p ffa +power-ups | 900 µs | 385 µs | 84 µs (78–93) | 15 µs (15–18) | 13 µs (12–14) | 68 µs (64–74) |
| decks 10p lives +power-ups | 1553 µs | 834 µs | 106 µs (100–114) | 18 µs (17–20) | 14 µs (14–17) | 85 µs (82–93) |

Sending as a share of all the server's work for a room (game with people playing + sending):

| scenario | json+deflate | json | bin | bin+deflate |
|---|---|---|---|---|
| classic 2p ffa | 13% | 5% | 5% | 12% |
| classic 4p ffa | 16% | 5% | 4% | 15% |
| platform 4p knockouts +power-ups | 9% | 3% | 3% | 8% |
| ramps 6p crown +power-ups | 11% | 3% | 2% | 10% |
| grand 8p ffa +power-ups | 18% | 4% | 3% | 15% |
| decks 10p lives +power-ups | 11% | 2% | 2% | 9% |

Bytes per player per message: payload / on the wire (with WebSocket, TLS, TCP and IP headers):

| scenario | json+deflate | json | bin | bin+deflate |
|---|---|---|---|---|
| classic 2p ffa | 36 / 112 B | 108 / 184 B | 35 / 111 B | 24 / 100 B |
| classic 4p ffa | 50 / 126 B | 145 / 223 B | 50 / 126 B | 32 / 108 B |
| platform 4p knockouts +power-ups | 43 / 119 B | 140 / 217 B | 52 / 128 B | 29 / 105 B |
| ramps 6p crown +power-ups | 65 / 141 B | 199 / 277 B | 67 / 143 B | 41 / 117 B |
| grand 8p ffa +power-ups | 77 / 153 B | 235 / 313 B | 75 / 151 B | 48 / 124 B |
| decks 10p lives +power-ups | 92 / 168 B | 277 / 355 B | 85 / 161 B | 57 / 133 B |
