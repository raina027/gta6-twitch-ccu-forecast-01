# Model notes — gta6-twitch-ccu-forecast-01

## What the program does

`main.py` reads one case (`/input/<id>.in`), takes the case's hour-1 print
`p1`, and forecasts hours 2–24 of the UTC release day as five quantiles
(5/25/50/75/95%) per hour. The only data it uses is inside the case file:
the `comparables` (past big launches' hourly Twitch curves, SullyGnome
hourly category averages) and the case's own hour-1 print.

## The model

For each comparable launch, take its release-day curve (24 whole hours from
its `day_start`) and form the log ratio to its hour-1 print,
`r_h = ln(viewers_h / viewers_1)`, for h = 2..24. Then, per hour, fit

    r_h = a_h + b_h * ln(p1)

by least squares across the usable comparables, with the slope shrunk 0.85×
toward 0 (few dozen launches, so raw slopes are noisy) and the intercept
re-centred. The fitted value is the median log ratio; the spread is that
hour's residual standard deviation shrunk 0.7×, times the standard normal
quantiles (−1.645, −0.674, 0, 0.674, 1.645). Quantiles are rounded to 2
decimals, half up, like the house baseline.

Why the hour-1 level predicts the shape: across the 37 usable comparables,
corr(ln(peak / hour-1), ln(hour-1)) ≈ −0.94. A launch that already draws a
huge crowd at midnight UTC (global unlock, or a big UK/EU base) has little
room left to grow; one that starts small is usually a rolling-midnight
launch whose big markets (the US, unlocking 05:00Z/08:00Z) only arrive
later, so it climbs steeply. GTA VI unlocks at rolling local midnight
(NZ 11:00Z Nov 18, CET 23:00Z, UK 00:00Z, US East 05:00Z, US Pacific
08:00Z), so the shape is exactly what this regression is built to infer
from the hour-1 print.

## What was tried and dropped

- Plain median ratio curve (no regression): practice loss 0.324, LOO 0.714.
  The median sits between flat and steep launches and fits neither.
- Gaussian spread at full residual std: worse than 0.7× shrinkage.
- Blending the regression with the median-ratio curve: worse on practice
  (0.217) and LOO (0.469).
- Filtering to "clean" comparables only (no early-access contamination):
  practice 0.189 but LOO 0.481 — the full set generalises better, so the
  program uses every comparable with a complete release day.
- Channels and pre-launch slope as extra features: correlations with the
  peak ratio beyond log(p1) are weak (−0.18 and −0.24), so they were left
  out. The program uses viewers only.

## Backtest numbers (author's own measurement)

Scorer: pinball loss on the log scale, exactly as the rules define it
(2·max(τ·d, (τ−1)·d), d = ln y − ln q). Practice answers are the same
public SullyGnome hourly figures the kit's cases come from, read once from
SullyGnome's public chart API for the four practice launch months.

| evaluation | this model | house baseline (persistence) |
|---|---|---|
| practice, 4 launches (mean) | **0.185** | 0.387 |
| practice, per launch | Wolverine 0.17, RDR2 0.17, GoW 0.20, Spider-Man 2 0.20 | 0.74 / 0.29 / 0.21 / 0.30 |
| leave-one-out, 41 launches (mean) | **0.43** | 0.88 |
| leave-one-out (median) | 0.29 | — |

The final case is one launch (GTA VI). The honest expectation is a loss in
the 0.17–0.30 range if its curve behaves like the practice launches, well
below the house baseline; the house model forecast's final loss is unknown.

## Dev leaderboard context (read 18 Nov 2026)

8,256 entries. The top ~340 have loss ≈ 0.000001 — practice-answer replays
(the practice answers are public SullyGnome data); the race seats the top
256 by dev rank, but the official result grades **every** final entry on
the frozen h00 recording, so a replay buys no prize. The best honest
(non-replay) entries sit around 0.05–0.10 on practice; this model scores
0.185 there, and its value is the final, where it uses the 42 comparables
the final case carries (including the four practice launches).

## Sources (all read, not assumed)

- Kit: `competition.yaml`, `RULES.txt`, `input/NOTICE.txt`, starter `main.py`
  (house baseline formula), `input/p00.in`–`p03.in` (comparables + practice
  cases).
- SullyGnome chart API, release months of the four practice launches
  (Marvel's Wolverine 2026-09, RDR2 2018-10, God of War Ragnarök 2022-11,
  Marvel's Spider-Man 2 2023-10) — "Average viewers" dataset; hour-1
  values match the cases' known prints exactly.
- Leaderboard: `GET /api/competitions/gta6-twitch-ccu-forecast-01/leaderboard`
  (8,256 entries, 18 Nov 2026).
- GTA VI unlock: rolling local midnight (competition.yaml); pre-release
  category probe 2026-11-17T03:10Z: 1,240 viewers, 181 channels
  (Twitch game id 1867279146).
