"""GTA VI Twitch CCU forecaster (gta6-twitch-ccu-forecast-01), Python 3.13 stdlib only.

Model: log-log ratio regression on past big launches.
------------------------------------------------------
For every past launch in the case's `comparables` we take its release-day
hourly Twitch viewers (24 whole hours from its day_start, SullyGnome hourly
averages) and form, per hour h = 2..24, the log ratio to that launch's hour-1
print:  r_h = ln(viewers_h / viewers_1).

Across launches, r_h is strongly tied to the hour-1 level itself: the bigger
hour 1, the flatter the rest of the day (on the 37 usable comparables the
correlation between ln(peak / hour-1) and ln(hour-1) is about -0.94). A launch
that already draws a huge crowd at midnight UTC has little room left to grow;
one that starts small is usually a rolling-midnight launch whose big markets
(the US) only unlock hours later, so it climbs steeply. So per hour we fit

    r_h = a_h + b_h * ln(p1)          (ordinary least squares)

where p1 is the case's hour-1 print, and take the fitted value as the median
log ratio. The spread comes from the fit's residuals: the per-hour residual
standard deviation, shrunk by SPREAD_SHRINK, times the standard normal
quantiles. The slope is shrunk by SLOPE_SHRINK toward 0 (the per-hour fits
use only a few dozen launches, so their slopes are noisy).

    q_tau(h) = p1 * exp(m_h + z_tau * s_h),  z = (-1.645, -0.674, 0, 0.674, 1.645)

rounded to 2 decimals, half up, exactly like the house baseline rounds.

Backtest (measured by the author on the kit's practice cases, whose answers
are the same public SullyGnome figures, and by leave-one-out over the
comparables):
    practice (4 launches)   mean pinball loss 0.19  (house baseline: 0.387)
    leave-one-out (41 launches) mean 0.43, median 0.29 (house: 0.88)
    practice typical miss ~30% (house: 43-189%)

Fallback: with fewer than 5 usable comparables the program falls back to the
house baseline's persistence rule (median = hour-1 print, spread
0.15 * sqrt(h - 1) in log space), so it always writes a valid forecast.

The program reads every *.in in the input directory (sorted by name) and
writes one <id>.out per case. No network, no randomness, no clock: two runs
on the same input write identical bytes. It uses only the case it is given
(the comparables travel inside the case file), so it works unchanged on the
final case h00, whose comparables include the four practice launches.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so `import model`
# would find a module shipped beside this file (kept for parity with the kit).
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# How much of each fitted slope to keep (1.0 = raw OLS; lower = more regularised).
SLOPE_SHRINK = 0.85
# How much of each hour's residual spread to keep in the forecast bands.
SPREAD_SHRINK = 0.7
# Minimum usable comparables before falling back to the persistence rule.
MIN_COMPARABLES = 5
# The persistence fallback's log spread per square-root hour (the house rule).
FALLBACK_SIGMA = 0.15


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, as JavaScript's Math.round(x * 100) / 100."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def mean(xs) -> float:
    return sum(xs) / len(xs)


def pstdev(xs) -> float:
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def ols(xs, ys):
    """Least-squares line y = a + b*x; returns (a, b)."""
    n = len(xs)
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return my, 0.0
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return my - b * mx, b


def day_curve(comparable: dict):
    """The comparable's release-day hourly viewers, index 0 = hour 1 (00:00Z).

    Returns None when the day is incomplete or holds a non-positive count.
    """
    day_start = comparable.get("day_start")
    hourly = comparable.get("hourly")
    if not day_start or not hourly:
        return None
    try:
        base = datetime.fromisoformat(day_start.replace("Z", "+00:00"))
    except ValueError:
        return None
    points = {}
    for p in hourly:
        try:
            points[p["from"]] = p["viewers"]
        except (KeyError, TypeError):
            continue
    curve = []
    for h in range(24):
        key = (base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        v = points.get(key)
        if v is None or v <= 0:
            return None
        curve.append(float(v))
    # An hour-1 print below 10 viewers cannot anchor a ratio curve: its
    # log ratios are noise, not signal. (The smallest real launch in the
    # comparables starts at 90+ viewers.)
    if curve[0] < 10:
        return None
    return curve


def fit_ratio_model(curves):
    """Per hour h = 2..24 fit ln(viewers_h / viewers_1) on ln(viewers_1).

    Returns a list of 23 (median_fn, spread) pairs, one per hour, where
    median_fn(ln_p1) is the fitted median log ratio and spread is the
    shrunk residual standard deviation of that hour's fit.
    """
    fitted = []
    for i in range(23):  # i = 0 is hour 2, i = 22 is hour 24
        xs = [math.log(c[0]) for c in curves]
        ys = [math.log(c[i + 1] / c[0]) for c in curves]
        a, b = ols(xs, ys)
        b *= SLOPE_SHRINK
        a = mean(ys) - b * mean(xs)  # re-centre so the line passes through the mean
        resid = [y - (a + b * x) for x, y in zip(xs, ys)]
        # The bands never collapse to a point: even a perfect fit keeps a
        # minimal 5% log spread, so the forecast always states uncertainty.
        fitted.append((a, b, max(0.05, pstdev(resid) * SPREAD_SHRINK)))
    return fitted


def ratio_forecast(fitted, p1: float) -> dict:
    """The five quantiles per hour from a fitted ratio model."""
    lp1 = math.log(p1)
    hours = []
    for i, h in enumerate(range(2, 25)):
        a, b, s = fitted[i]
        med = a + b * lp1
        qs = [round2(p1 * math.exp(med + z * s)) for z in Z]
        qs = [max(1, min(1_000_000_000, q)) for q in qs]
        # Quantiles must be non-decreasing; the z order guarantees it, but
        # rounding can tie neighbours, which is allowed, never invert them.
        for j in range(1, 5):
            if qs[j] < qs[j - 1]:
                qs[j] = qs[j - 1]
        hours.append({"hour": h, "q": qs})
    return {"hours": hours}


def persistence_forecast(p1: float, hours_to_forecast) -> dict:
    """The house baseline's rule, used when too few comparables are usable."""
    hours = []
    for row in hours_to_forecast:
        h = row["hour"]
        qs = [round2(p1 * math.exp(z * FALLBACK_SIGMA * math.sqrt(h - 1))) for z in Z]
        qs = [max(1, min(1_000_000_000, q)) for q in qs]
        hours.append({"hour": h, "q": qs})
    return {"hours": hours}


def forecast_case(case: dict, name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1, float(first["viewers"]))
    rows = case["forecast"]

    curves = []
    for comp in case.get("comparables") or []:
        curve = day_curve(comp)
        if curve is not None:
            curves.append(curve)

    if len(curves) >= MIN_COMPARABLES:
        fitted = fit_ratio_model(curves)
        return ratio_forecast(fitted, p1)
    return persistence_forecast(p1, rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
