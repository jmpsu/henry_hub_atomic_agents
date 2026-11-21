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


def catalog_domain_series(conn, domain: str, as_of: str, since: str, measured_only: bool = True) -> dict:
    from series_catalog import active_agents
    return {a: pit_series(conn, a, as_of, since, measured_only=measured_only) for a in active_agents(conn, domain=domain)}


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


# ----------------------------------------------------------------------------- cross-domain features (PIT at every origin)
def pit_rows(conn, agent_id, as_of, since="1990-01-01T00:00:00Z"):
    """[(target_date, value, available_timestamp)] for one agent, latest vintage per target known at as_of, sorted by target."""
    as_of = ingest.utc_iso(as_of)
    rows = conn.execute(
        "SELECT p.target_timestamp,p.value,p.available_timestamp FROM pit_market_data p WHERE p.agent_id=? AND p.available_timestamp<=? "
        "AND p.target_timestamp>=? AND COALESCE(p.provenance,'measured')='measured' AND p.available_timestamp=(SELECT MAX(q.available_timestamp) "
        "FROM pit_market_data q WHERE q.agent_id=p.agent_id AND q.target_timestamp=p.target_timestamp AND q.available_timestamp<=?) "
        "ORDER BY p.target_timestamp", (agent_id, as_of, since, as_of)).fetchall()
    assert all(r[2] <= as_of for r in rows), "LOOK-AHEAD: feature row published after decision time"
    return [(r[0][:10], r[1], r[2]) for r in rows]


class KnownAt:
    """value_at(ts): the latest-target value whose available_timestamp <= ts. Used to build each TRAINING origin's feature
    as it was known on that origin day, so fitting never uses data published later than the origin."""

    def __init__(self, rows):
        import bisect
        self._b = bisect
        ev = sorted((r[2], r[0], r[1]) for r in rows)        # by availability
        self.av, best, self.val = [], None, []
        for a, t, v in ev:
            if best is None or t >= best[0]:
                best = (t, v)
            self.av.append(a)
            self.val.append(best)

    def at(self, ts):
        i = self._b.bisect_right(self.av, ts) - 1
        return self.val[i] if i >= 0 else None


def _close(d):
    return d + "T21:00:00Z"


def crude_features(conn, t, horizon_days, lookback_days=900):
    since = _iso(_dt(ingest.utc_iso(t)) - timedelta(days=lookback_days))
    return {"horizon_days": horizon_days, "wti": KnownAt(pit_rows(conn, "Agent_Crude_WTI_Spot", t, since))}


PROD_BASINS = ("Agent_Prod_Appalachia", "Agent_Prod_Permian", "Agent_Prod_Haynesville", "Agent_Prod_EagleFord", "Agent_Prod_Bakken", "Agent_Prod_DJBasin")


def production_features(conn, t, horizon_days, lookback_days=1500):
    since = _iso(_dt(ingest.utc_iso(t)) - timedelta(days=lookback_days))
    by = {}
    for a in PROD_BASINS:
        for d, v, av in pit_rows(conn, a, t, since):
            e = by.setdefault(d, [0.0, 0, ""])
            e[0] += v; e[1] += 1; e[2] = max(e[2], av)
    months = sorted((d, v, av) for d, (v, n, av) in by.items() if n == len(PROD_BASINS))
    # 3-month change in total shale output, stamped with the availability of the newer month
    chg = [(months[i][0], months[i][1] - months[i - 3][1], max(months[i][2], months[i - 3][2])) for i in range(3, len(months))]
    return {"horizon_days": horizon_days, "prod_chg3": KnownAt(chg)}


def _ols_forecast(history, h, x_at, min_obs=60):
    """Fit (price at origin+h) - (price at origin) = a + b*x(origin) on the visible history, return last + a + b*x(now)."""
    if not history:
        return None
    last = history[-1][1]
    px = {d[:10]: v for d, v in history}
    xs, ys = [], []
    for d, v in px.items():
        fut = px.get((_dt(d + "T00:00:00Z") + timedelta(days=h)).strftime("%Y-%m-%d"))
        x = x_at(d, v)
        if fut is not None and x is not None:
            xs.append(x); ys.append(fut - v)
    x_now = x_at(history[-1][0][:10], last)
    if len(xs) < min_obs or x_now is None:
        return last
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return last
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return last + (my - b * mx) + b * x_now


def propane_wti_revert(history, features):
    """Propane (cents/gal) vs WTI ($/bbl): regress the h-day propane change on the gap between today's price and the price
    implied by the trailing-60-session average propane/WTI ratio. Every ratio uses WTI as known on that origin day."""
    if not features:
        return history[-1][1] if history else None
    wti, h = features["wti"], int(features["horizon_days"])
    vals = [v for _, v in history]
    dates = [d[:10] for d, _ in history]
    ratios = []
    for d, v in zip(dates, vals):
        w = wti.at(_close(d))
        ratios.append(v / 100 * 42 / w[1] if w and w[1] > 0 else None)
    idx = {d: i for i, d in enumerate(dates)}

    def x_at(d, v):
        i = idx[d]
        win = [r for r in ratios[max(0, i - 60):i] if r is not None]
        w = wti.at(_close(d))
        if len(win) < 30 or not w:
            return None
        return (sum(win) / len(win)) * w[1] / 42 * 100 - v            # fair price minus actual (cents/gal)
    return _ols_forecast(history, h, x_at)


def propane_wti_momentum(history, features):
    """Regress the h-day propane change on the 5-day WTI return known at the origin."""
    if not features:
        return history[-1][1] if history else None
    wti, h = features["wti"], int(features["horizon_days"])

    def x_at(d, v):
        now, then = wti.at(_close(d)), wti.at(_close((_dt(d + "T00:00:00Z") - timedelta(days=7)).strftime("%Y-%m-%d")))
        return (now[1] / then[1] - 1) if now and then and then[1] > 0 else None
    return _ols_forecast(history, h, x_at)


def hh_production_momentum(history, features):
    """Regress the h-day Henry Hub change on the 3-month change in shale gas output as published by the origin day."""
    if not features:
        return history[-1][1] if history else None
    pc, h = features["prod_chg3"], int(features["horizon_days"])
    return _ols_forecast(history, h, lambda d, v: (pc.at(_close(d)) or (None, None))[1], min_obs=120)


def walk_forward(conn, target_agent, decision_times, horizon_days, model, cost_bps=0.0, eval_lag_days=1, feature_fn=None, slippage_bps=0.0):
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
        ret = sig * (actual - last) / (abs(last) or 1.0) - (cost_bps + slippage_bps) / 1e4 * (1 if sig else 0)
        out.append({"decision": t, "target": target_ts, "pred": pred, "actual": actual, "last": last,
                    "dir_hit": (sig == ((actual > last) - (actual < last))) if sig else None, "ret": ret})
    return out


def split_chronological(rows, train=0.5, validation=0.25):
    """Strictly ordered train/validation/test; the final block is the untouched holdout."""
    n = len(rows)
    a, b = int(n * train), int(n * (train + validation))
    return rows[:a], rows[a:b], rows[b:]


def _risk(rows):
    """Path statistics of the per-decision returns (after costs and slippage). Sharpe is per decision, NOT annualised,
    and overlapping multi-day horizons make consecutive returns correlated, so treat it as indicative only."""
    r = [x["ret"] for x in rows]
    if not r:
        return {"max_drawdown": None, "sharpe_per_decision": None}
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in r:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    mean = sum(r) / len(r)
    var = sum((x - mean) ** 2 for x in r) / (len(r) - 1) if len(r) > 1 else 0.0
    return {"max_drawdown": dd, "sharpe_per_decision": (mean / math.sqrt(var)) if var > 0 else None}


def regime(target_ts: str) -> str:
    """Market regime by the forecast target month: heating season (Nov-Mar) vs the rest of the year."""
    return "heating_season" if int(target_ts[5:7]) in (11, 12, 1, 2, 3) else "non_heating_season"


def metrics(rows, by_regime=True):
    if not rows:
        return {"n": 0}
    e = [r["pred"] - r["actual"] for r in rows]
    hits = [r["dir_hit"] for r in rows if r["dir_hit"] is not None]
    out = {"n": len(rows), "rmse": math.sqrt(sum(x * x for x in e) / len(e)), "mae": sum(abs(x) for x in e) / len(e),
           "bias": sum(e) / len(e), "directional_hit_rate": (sum(hits) / len(hits)) if hits else None,
           "mean_return_after_costs": sum(r["ret"] for r in rows) / len(rows),
           "persistence_rmse": math.sqrt(sum((r["last"] - r["actual"]) ** 2 for r in rows) / len(rows)), **_risk(rows)}
    if by_regime:
        out["by_regime"] = {g: {k: v for k, v in metrics([r for r in rows if regime(r["target"]) == g], by_regime=False).items()
                                if k in ("n", "rmse", "persistence_rmse", "directional_hit_rate", "mean_return_after_costs", "max_drawdown")}
                            for g in ("heating_season", "non_heating_season")}
    return out
