"""Point-in-time walk-forward backtester (local compute). Every model input is built from
ingest.pit_snapshot(conn, decision_time); the engine asserts no row with available_timestamp >
decision_time is ever visible to a model. Actuals are read at evaluation time, never at decision time."""
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import ingest


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _iso(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def persistence(history, features):
    """Baseline: next value equals the last value known at decision time."""
    return history[-1][1] if history else None


def ar1(history, features):
    """AR(1) on first differences, fitted ONLY on the history visible at decision time."""
    v = [x[1] for x in history]
    if len(v) < 4:
        return v[-1] if v else None
    d = [b - a for a, b in zip(v, v[1:])]
    num = sum(x * y for x, y in zip(d, d[1:]))
    den = sum(x * x for x in d[:-1]) or 1.0
    return v[-1] + (num / den) * d[-1]


def pit_series(conn, agent_id, as_of, since, measured_only=True):
    """{YYYY-MM-DD: value} for one agent as known at as_of (latest vintage with available_timestamp <= as_of), target >= since."""
    as_of = ingest.utc_iso(as_of)
    q = ("SELECT p.target_timestamp,p.value,p.available_timestamp FROM pit_market_data p WHERE p.agent_id=? AND p.available_timestamp<=? "
         "AND p.target_timestamp>=? AND p.available_timestamp=(SELECT MAX(q.available_timestamp) FROM pit_market_data q "
         "WHERE q.agent_id=p.agent_id AND q.target_timestamp=p.target_timestamp AND q.available_timestamp<=?)")
    if measured_only:
        q += " AND COALESCE(p.provenance,'measured')='measured'"
    rows = conn.execute(q, (agent_id, as_of, since, as_of)).fetchall()
    assert all(r[2] <= as_of for r in rows), "LOOK-AHEAD: feature row published after decision time"
    return {r[0][:10]: r[1] for r in rows}


def weather_features(conn, t, horizon_days, lookback_days=420):
    """Cross-domain feature set visible at decision time t: CONUS HDD anomaly = observed HDD - 30-year normal HDD.
    The normal is a derived estimate (provenance extracted_estimate), so it is read with measured_only=False."""
    since = _iso(_dt(ingest.utc_iso(t)) - timedelta(days=lookback_days))
    hdd = pit_series(conn, "Agent_Weather_Actual_HDD", t, since)
    norm = pit_series(conn, "Agent_Weather_30YrNormal_HDD", t, since, measured_only=False)
    return {"horizon_days": horizon_days, "hdd_anomaly": {d: hdd[d] - norm[d] for d in hdd if d in norm}}


def hdd_anomaly(history, features):
    """Price change over the horizon regressed (OLS, fitted only on data visible at decision time) on the latest HDD anomaly
    known before each origin day. Falls back to the last price (no signal) when there is too little aligned history."""
    if not history:
        return None
    last = history[-1][1]
    anom = (features or {}).get("hdd_anomaly") or {}
    h = int((features or {}).get("horizon_days", 1))
    px = {d[:10]: v for d, v in history}
    day = lambda s, n: (_dt(s + "T00:00:00Z") + timedelta(days=n)).strftime("%Y-%m-%d")
    xs, ys = [], []
    for d, v in px.items():
        x, fut = anom.get(day(d, -1)), px.get(day(d, h))
        if x is not None and fut is not None:
            xs.append(x); ys.append(fut - v)
    x_now = anom.get(day(history[-1][0][:10], -1))
    if len(xs) < 40 or x_now is None:
        return last
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return last
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return last + (my - b * mx) + b * x_now


def walk_forward(conn, target_agent, decision_times, horizon_days, model, cost_bps=0.0, eval_lag_days=1, feature_fn=None):
    """For each decision time t: build history from the PIT snapshot at t, predict the value for target
    time t+horizon, and score it against the value known at (target+eval_lag), i.e. after the target is published."""
    out = []
    for t in decision_times:
        snap = ingest.pit_snapshot(conn, t, [target_agent])
        assert all(r[2] <= ingest.utc_iso(t) for r in snap), "LOOK-AHEAD: row published after decision time"
        history = sorted((r[1], r[3]) for r in snap)
        if len(history) < 2:
            continue
        pred = model(history, feature_fn(conn, t, horizon_days) if feature_fn else None)
        # forecast target lies on the series' own timeline: last known target + horizon
        target_ts = _iso(_dt(history[-1][0]) + timedelta(days=horizon_days))
        eval_at = _iso(_dt(target_ts) + timedelta(days=eval_lag_days))
        later = [r for r in ingest.pit_snapshot(conn, eval_at, [target_agent]) if r[1] == target_ts]
        if pred is None or not later:
            continue
        actual, last = later[0][3], history[-1][1]
        sig = (pred > last) - (pred < last)
        ret = sig * (actual - last) / (abs(last) or 1.0) - cost_bps / 1e4 * (1 if sig else 0)
        out.append({"decision": t, "target": target_ts, "pred": pred, "actual": actual, "last": last,
                    "dir_hit": (sig == ((actual > last) - (actual < last))) if sig else None, "ret": ret})
    return out


def split_chronological(rows, train=0.5, validation=0.25):
    """Strictly ordered train/validation/test; the final block is the untouched holdout."""
    n = len(rows)
    a, b = int(n * train), int(n * (train + validation))
    return rows[:a], rows[a:b], rows[b:]


def metrics(rows):
    if not rows:
        return {"n": 0}
    e = [r["pred"] - r["actual"] for r in rows]
    hits = [r["dir_hit"] for r in rows if r["dir_hit"] is not None]
    return {"n": len(rows), "rmse": math.sqrt(sum(x * x for x in e) / len(e)), "mae": sum(abs(x) for x in e) / len(e),
            "bias": sum(e) / len(e), "directional_hit_rate": (sum(hits) / len(hits)) if hits else None,
            "mean_return_after_costs": sum(r["ret"] for r in rows) / len(rows),
            "persistence_rmse": math.sqrt(sum((r["last"] - r["actual"]) ** 2 for r in rows) / len(rows))}
