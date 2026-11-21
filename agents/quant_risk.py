"""Quantitative Risk Management Engine (QUANT_HUB_SPEC section 4).

VaR at four estimation paths (parametric/Gaussian, historical simulation, Monte Carlo) and Expected
Shortfall (CVaR) for each. All VaR/ES magnitudes are positive expected losses in the worst ~alpha tail
(100 * alpha %). Stress testing: Winter Storm Uri freeze scenario, pipeline outage shock, multi-factor
commodity price shifts. Capital & margin: initial/variation margin modeling, liquidity-buffer estimation.

Every input series is point-in-time ([(date, price, available_timestamp)] from markets_engine.load_series);
every returned figure is computed from the given series only.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np


def _stats(arr):
    arr = np.asarray(arr, dtype=float)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    return mu, sigma


def _phi(z: float) -> float:
    return math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
# ----------------------------------------------------------------------------- VaR (4 paths)
def var_parametric(returns, alpha: float = 0.05) -> float:
    """Gaussian parametric VaR: the alpha-quantile of returns, returned as a positive loss magnitude,
    clamped at 0 when the expected loss is non-positive. z = NormalDist().inv_cdf(alpha) < 0 for alpha < 0.5."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        raise ValueError("returns must be non-empty")
    mu, sigma = _stats(arr)
    q = mu + NormalDist().inv_cdf(alpha) * sigma                      # alpha-quantile of returns
    return max(-q, 0.0)


def var_historical(returns, alpha: float = 0.05) -> float:
    """Historical simulation VaR: the (100 - 100*alpha)-th percentile of losses, i.e. losses[n - k],
    so the worst ~alpha fraction lies above the threshold."""
    losses = np.sort(-np.asarray(returns, dtype=float))
    k = min(max(int(alpha * len(losses)), 1), len(losses))
    return float(losses[len(losses) - k])


def var_montecarlo(returns, alpha: float = 0.05, n_sims: int = 10_000, seed: int = 20261119) -> float:
    """Monte Carlo VaR: worst ~100 * alpha % of simulated Gaussian returns (mu/sigma of the series)."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        raise ValueError("returns must be non-empty")
    mu, sigma = _stats(arr)
    rng = np.random.default_rng(seed)
    sim = rng.normal(mu, sigma, n_sims)
    return max(-np.percentile(sim, 100 * alpha), 0.0)


# ----------------------------------------------------------------------------- ES (Expected Shortfall / CVaR)
def cvar_parametric(returns, alpha: float = 0.05) -> float:
    """Gaussian expected shortfall: mean of returns strictly worse than the parametric VaR (positive magnitude)."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        raise ValueError("returns must be non-empty")
    var = -var_parametric(arr, alpha)
    worse = arr[arr < var]
    return max(-float(worse.mean()), 0.0) if len(worse) else 0.0


def cvar_historical(returns, alpha: float = 0.05) -> float:
    """Historical expected shortfall: mean of the worst ~alpha fraction of losses (>= VaR)."""
    losses = np.sort(-np.asarray(returns, dtype=float))
    k = min(max(int(alpha * len(losses)), 1), len(losses))
    return float(np.mean(losses[len(losses) - k:]))


def cvar_montecarlo(returns, alpha: float = 0.05, n_sims: int = 10_000, seed: int = 20261119) -> float:
    """Monte Carlo expected shortfall: mean of simulated returns below the VaR level."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        raise ValueError("returns must be non-empty")
    mu, sigma = _stats(arr)
    rng = np.random.default_rng(seed)
    sim = rng.normal(mu, sigma, n_sims)
    var = -np.percentile(sim, 100 * alpha)
    tail = sim[sim < -var]                                         # returns worse than the VaR loss threshold
    return float(-tail.mean()) if len(tail) else max(var, 0.0)


# ----------------------------------------------------------------------------- stress scenarios
def winter_storm_uri_freeze_scenario(hh_series, duration_days: int = 30, spot_drop: float = 0.35,
                                     name: str = "Winter Storm Uri freeze") -> dict:
    """Sustained cold snap: Henry Hub spot drops by `spot_drop` of its last vintage over `duration_days`
    (modeled on the 2021 Texas freeze), then stays depressed. Returns {"series": [(date, price)], "description"}."""
    s = sorted(hh_series, key=lambda x: x[0])
    if not s:
        return {"series": [], "description": f"{name}: no Henry Hub spot series to project."}
    base = float(s[-1][1]) * (1 - spot_drop)
    out = [(s[-1][0], max(base, 0.0))]
    d0 = date.fromisoformat(s[-1][0])
    for d in range(1, duration_days + 1):
        out.append(((d0 + timedelta(days=d)).isoformat(), base))
    return {"series": out, "description": f"{name}: HH spot holds {base:.2f} for {duration_days} days after a {spot_drop:.0%} freeze-to-last-vintage drop."}


def pipeline_outage_shock(hh_series, hh_delta: float = 0.08, duration_days: int = 7,
                          name: str = "pipeline outage shock") -> dict:
    """Constrained-flow shock: Henry Hub spot steps up by `hh_delta` per day for `duration_days`, then stays.
    Returns {"series": [(date, price)], "description"}."""
    s = sorted(hh_series, key=lambda x: x[0])
    if not s:
        return {"series": [], "description": f"{name}: no Henry Hub spot series to project."}
    d0, price = date.fromisoformat(s[-1][0]), float(s[-1][1])
    out = [(s[-1][0], price)]
    for d in range(1, duration_days + 1):
        price += hh_delta
        out.append(((d0 + timedelta(days=d)).isoformat(), price))
    return {"series": out, "description": f"{name}: HH spot +{hh_delta}/day for {duration_days} days."}


def multi_factor_shift(hh_series, natural_gas_pct: float = 0.0, duration_days: int = 30,
                       name: str = "multi-factor commodity price shifts") -> dict:
    """Multi-factor shift: Henry Hub spot steps by `natural_gas_pct` % for `duration_days`, then stays.
    Returns {"series": [(date, price)], "description"}."""
    s = sorted(hh_series, key=lambda x: x[0])
    if not s:
        return {"series": [], "description": f"{name}: no Henry Hub spot series to project."}
    d0, price = date.fromisoformat(s[-1][0]), float(s[-1][1])
    out = [(s[-1][0], price)]
    for d in range(1, duration_days + 1):
        price = price * (1 + natural_gas_pct)
        out.append(((d0 + timedelta(days=d)).isoformat(), price))
    out += [((d0 + timedelta(days=duration_days + t)).isoformat(), price) for t in range(1, 6)]
    return {"series": out, "description": f"{name}: HH spot +{natural_gas_pct:.0%}/day for {duration_days} days."}


# ----------------------------------------------------------------------------- capital & margin
def initial_margin(notional: float, margin_rate: float = 0.06) -> float:
    """Initial margin on a position: margin_rate of the notional."""
    return notional * margin_rate


def variation_margin_path(returns, notional: float) -> list:
    """Cumulative variation margin path: running sum of returns * notional (positive = margin due)."""
    return (np.cumsum(np.asarray(returns, dtype=float)) * notional).tolist()


def liquidity_buffer(var_magnitude: float, horizon_days: int = 20, multiplier: float = 3.0) -> float:
    """Conservative liquidity buffer: multiplier * expected VaR, scaled by sqrt(horizon_days)."""
    return multiplier * var_magnitude * math.sqrt(horizon_days)
