"""Definitions, formulas and parameters behind every figure on the dashboard, served in the API as `explain`.

Parameters are read from the real function signatures and constants in markets_engine (inspect.signature), so a change to a window, period or
threshold changes the documentation with it, and tests/test_metric_docs.py fails if they ever disagree. Text here is static documentation:
it contains no market values. Live values, timestamps and lineage come from the payload itself.
"""
from __future__ import annotations

import inspect
from typing import Callable

import lng_config as lc
import lng_forward as lf
import lng_global as lg


def _d(fn: Callable, name: str):
    return inspect.signature(fn).parameters[name].default


def build(me) -> dict:
    """me = the markets_engine module (passed in to avoid a circular import)."""
    rsi_p, macd_f, macd_s, macd_g = _d(me.rsi, "period"), _d(me.macd, "fast"), _d(me.macd, "slow"), _d(me.macd, "signal")
    bb_w, bb_k, bb_q = _d(me.bollinger, "window"), _d(me.bollinger, "k"), _d(me.bollinger, "squeeze_pct")
    fast, slow = _d(me.ma_crossovers, "fast"), _d(me.ma_crossovers, "slow")
    sw = _d(me.swing_points, "window")
    tri_lb, tri_flat = _d(me.triangle_detection, "lookback"), _d(me.triangle_detection, "flat_pct_per_bar")
    dv_w, dv_lb = _d(me._divergence, "window"), _d(me._divergence, "lookback")
    yrs, step = _d(me.seasonal_overlay, "years_back"), _d(me.seasonal_overlay, "step")
    band = _d(me.curve_regime, "flat_band")
    ratios = ", ".join(f"{r * 100:.1f}%" for r in me.FIB_RATIOS)

    def doc(title, what, formula=None, params=None, read=None, caveat=None):
        return {"title": title, "what": what, "formula": formula, "params": params or {}, "read": read, "caveat": caveat}

    out = {
        # ---- price and changes
        "price": doc("Last price", "The most recent price observation for the selected product that was available at the cutoff shown at the top of the page.",
                     "value of the latest observation date; if the source revised it, the latest vintage with available time <= the cutoff",
                     read="Source, observation date and the times it was retrieved and became available are listed under Data lineage.",
                     caveat="Daily spot series from EIA are published with a lag, so the price date can be several days behind today. Futures quotes are a different series and are never mixed into spot."),
        "change_1d": doc("1-day change", "Difference between the last price and the previous trading session in the same series.", "last - previous session; % = last / previous - 1"),
        "change_5d": doc("5-day change", "Difference between the last price and the price five sessions earlier in the same series.", "last - price 5 sessions earlier; % = last / that price - 1"),
        "price_date": doc("Price date", "Target (observation) date of the latest price: the day the price refers to, not the day it was collected.",
                          caveat="Compare with 'Available': that is when this system could first have used the value."),
        # ---- trend and momentum
        "sma50": doc("50-day average", f"Simple moving average of the last {fast} sessions' closes, computed on the full history, not just the visible window.", f"sum of last {fast} closes / {fast}"),
        "sma200": doc("200-day average", f"Simple moving average of the last {slow} sessions' closes, computed on the full history.", f"sum of last {slow} closes / {slow}",
                      caveat=f"Needs {slow} sessions of history; blank before that."),
        "trend": doc("Trend", "Whether the last price is above or below the 200-day average.", "above_200dma if last > 200-day average, else below_200dma"),
        "ma_regime": doc("50/200 regime", "Golden cross regime when the 50-day average is above the 200-day average; death cross regime when below.",
                         "golden if 50-day > 200-day, death if 50-day < 200-day", read="The tag marks the regime, not the day the lines crossed. Crossover dates are the markers on the price chart."),
        "crossover": doc("Moving-average crossover", f"A day the {fast}-day average crossed the {slow}-day average.", f"golden cross: {fast}-day crosses above {slow}-day; death cross: crosses below"),
        "rsi14": doc("RSI (14)", f"Wilder Relative Strength Index over {rsi_p} sessions: momentum on a 0-100 scale.",
                     f"RSI = 100 - 100 / (1 + RS); RS = Wilder-smoothed average gain / average loss over {rsi_p} sessions", {"period": rsi_p},
                     read="Conventionally above 70 is stretched to the upside and below 30 to the downside (the dotted lines on the chart). It describes momentum, not value."),
        "macd": doc(f"MACD ({macd_f}, {macd_s}, {macd_g})", "Trend-following momentum: the gap between a fast and a slow exponential average, its signal line and the histogram.",
                    f"line = EMA{macd_f} - EMA{macd_s}; signal = EMA{macd_g} of the line; histogram = line - signal", {"fast": macd_f, "slow": macd_s, "signal": macd_g},
                    read="A positive histogram means the line is above its signal (momentum rising); negative means falling."),
        "macd_hist": doc("MACD histogram", "MACD line minus its signal line for the last session.", f"(EMA{macd_f} - EMA{macd_s}) - EMA{macd_g} of that difference"),
        "bandwidth": doc("Bollinger bandwidth", f"Width of the Bollinger bands as a percent of their midline. Bands are the {bb_w}-day average +/- {bb_k} standard deviations.",
                         f"(upper - lower) / mid * 100; mid = {bb_w}-day average; upper/lower = mid +/- {bb_k} sigma", {"window": bb_w, "sigma": bb_k},
                         read="Narrow bands mean unusually low recent volatility."),
        "squeeze": doc("Bollinger squeeze", f"Flag set when bandwidth is at or below its own {bb_q:.0f}th percentile over the history, i.e. unusually narrow.",
                       f"bandwidth <= {bb_q:.0f}th percentile of historical bandwidth", {"percentile": bb_q},
                       caveat="A squeeze says volatility is low; it does not say which way price will move."),
        "triangle": doc("Triangle pattern", f"Converging trend lines fitted through recent swing highs and swing lows over the last {tri_lb} sessions (or the window if shorter).",
                        f"least-squares line through swing highs and through swing lows (a swing = extreme of +/-{sw} bars); the lines must converge; a side is flat when its slope is under {tri_flat}% of the mean price per bar",
                        {"lookback": tri_lb, "swing_window": sw, "flat_pct_per_bar": tri_flat},
                        read="ascending = flat top with rising lows; descending = flat bottom with falling highs; symmetrical = falling highs and rising lows. 'none' means no converging pattern was found.",
                        caveat="A fitted pattern is a description of recent prices, not a forecast."),
        "breakout": doc("Triangle breakout / breakdown level", "Where the upper (breakout) or lower (breakdown) triangle line sits at the last session.", "value of the fitted upper / lower line at the last bar"),
        "divergence_rsi": doc("RSI divergence", f"Price and RSI disagree at the last two swing points within the last {dv_lb} sessions.",
                              f"bearish: price makes a higher swing high while RSI makes a lower one; bullish: price makes a lower swing low while RSI makes a higher one (swing window {dv_w})",
                              {"swing_window": dv_w, "lookback": dv_lb}, caveat="Divergences can persist for many sessions before, or without, a turn."),
        "divergence_macd": doc("MACD divergence", f"Same test as RSI divergence applied to the MACD line, over the last {dv_lb} sessions.", "price swing high vs MACD-line swing high (bearish) or swing low vs swing low (bullish)",
                               {"swing_window": dv_w, "lookback": dv_lb}),
        "swing_high": doc("Swing high", "Highest price in the visible window; the top anchor of the Fibonacci grid.", "max of closes in the window"),
        "swing_low": doc("Swing low", "Lowest price in the visible window; the bottom anchor of the Fibonacci grid.", "min of closes in the window"),
        "fib_level": doc("Fibonacci retracement level", f"A price at a standard fraction of the swing range ({ratios}).",
                         "up-leg (low before high): level = high - range * ratio; down-leg: level = low + range * ratio; range = high - low",
                         read="Traders watch these prices as possible support or resistance; there is no mechanical reason price must respect them."),
        "fib_marker": doc("Where price sits in the range", "The last price positioned along the swing range as a percent retraced.",
                          "retraced % = (high - last) / range * 100 in an up-leg; (last - low) / range * 100 in a down-leg"),
        "golden_ratio": doc("Golden ratio proximity", "Distance between the last price and the 61.8% level, as a percent of the swing range.", "|last - level 61.8%| / range * 100"),
        "seasonal_band": doc("Seasonal overlay", f"Each prior year's path aligned by calendar day, with the min-max band and average of the previous {yrs} complete years; this year's path is drawn in gold.",
                             f"sampled every {step} days; years with fewer than 150 observations are excluded", {"years_back": yrs, "step_days": step},
                             read="Where the gold line leaves the band, this year is outside the range of the past five."),
        # ---- relative value
        "pct_of_wti": doc("NGL as % of WTI crude", "The NGL price converted to dollars per barrel and expressed as a percent of WTI crude.",
                          f"(cents/gal / 100 * {me.GAL_PER_BBL:g}) / WTI USD/bbl * 100", {"gallons_per_barrel": me.GAL_PER_BBL},
                          read="Higher means the NGL is richer relative to crude (closer to crude-parity value).", caveat="Needs both an NGL series and WTI for the same dates."),
        "wti": doc("WTI crude (Cushing)", "West Texas Intermediate spot price, the crude benchmark used as the denominator of the NGL-to-crude ratio.", caveat="EIA daily spot; published with a lag."),
        "frac_spread": doc("Frac spread", "The value of ethane as fuel (per MMBtu) minus Henry Hub gas.",
                           f"(ethane cents/gal / 100) / {me.ETHANE_MMBTU_PER_GAL} - Henry Hub USD/MMBtu", {"mmbtu_per_gallon_ethane": me.ETHANE_MMBTU_PER_GAL},
                           read="Positive favours recovering ethane from the gas stream; negative favours leaving it in (rejection).",
                           caveat="Withheld until a real Mont Belvieu ethane series exists; it is never estimated."),
        "fundamental_element": doc("Fundamental element", "One of the seven physical drivers of the natural-gas balance, classified as a direct ingested input (used as published, only aligned to the point-in-time cutoff) or a "
                                   "separately calculated module (computed in its own isolated step before the pricing engine).",
                                   read="The headline is the newest value available at the cutoff; blocked inputs list the exact missing feed and the step that would activate it.",
                                   caveat="None of these elements enters the Henry Hub forward curve or the LNG forward price shown on this page (checklist O6: no fundamentals-to-price model exists); they are context."),
        "hub_spread": doc("Mont Belvieu minus Conway", "Price difference for propane between the Gulf Coast hub and the Midcontinent hub.", "Mont Belvieu cents/gal - Conway cents/gal",
                          caveat="Withheld until a real Conway series exists."),
        # ---- forward curve
        "forward_curve": doc("Henry Hub forward curve", "Prices of the next 12 monthly NYMEX natural gas futures contracts, M1 (prompt) to M12, for one quote date.",
                             "one point per contract; contract month = the delivery month in the contract symbol", {"flat_band": band},
                             read="Futures only: spot prices are never mixed into this curve.", caveat="Values are delayed, unofficial quotes, not exchange settlements."),
        "regime": doc("Curve regime", f"How the curve is classified. SEASONAL: a curve of 6+ contracts that reverses direction at least twice (moves under {band} are ignored), so the last minus the first compares different calendar months. Otherwise CONTANGO if the back is above the front by more than {band}, BACKWARDATION if below, FLAT if within.",
                      f"SEASONAL if reversals >= 2 (6+ contracts); else sign of (last - first) beyond {band}", {"flat_band": band}),
        "fwd_point": doc("Futures contract", "One monthly NYMEX contract on the forward curve.", read="Hover shows the contract symbol, delivery month and where the quote came from."),
        # ---- LNG (all numbers below come from lng_config, the single place for assumptions)
        "lng_forward": doc("LNG forward cost curve (US Gulf FOB)", "An estimate of what it costs to deliver LNG free-on-board from the U.S. Gulf Coast for each of the next 12 months, built from the Henry Hub futures curve plus a liquefaction fee.",
                           f"FOB cost = {lc.FEEDGAS_FACTOR:g} x Henry Hub futures + {lc.LIQUEFACTION_FEE_USD_MMBTU:g} (USD/MMBtu)", {"feedgas_factor": lc.FEEDGAS_FACTOR, "liquefaction_fee_usd_mmbtu": lc.LIQUEFACTION_FEE_USD_MMBTU},
                           read="A cost estimate, not a quote and not a price anyone can trade at. Set it against a destination price (the netback) to see the margin.",
                           caveat="The feed-gas factor and the liquefaction fee default to labelled assumptions set in lng_config.py, not market data. A value from the knowledge library replaces a default only if a verbatim quote stored there contains that number (x100 for a percentage), it lies inside a sanity band, and the parameters file was available at the cutoff; the quote is then shown. No generated text sets a number. The Henry Hub inputs are delayed, unofficial quotes. Provenance: extracted estimate."),
        "lng_fwd_point": doc("LNG cost for one month", "The LNG cost for one delivery month with every step shown: the Henry Hub contract for that month, the feed-gas cost, the liquefaction fee and the total.",
                             f"FOB cost = {lc.FEEDGAS_FACTOR:g} x Henry Hub + {lc.LIQUEFACTION_FEE_USD_MMBTU:g}",
                             read="Under Data lineage is the Henry Hub quote this month is built from: its source, when it was published, and when this system could first use it.",
                             caveat="A month with no Henry Hub point has no value; nothing is filled in."),
        "lng_netback": doc("Netback from TTF", "What a cargo sold at the Dutch TTF price nets back to the U.S. Gulf after shipping and regasification, and its margin over the FOB cost.",
                           lf.NETBACK_FORMULA, {"shipping_usd_mmbtu": lc.SHIPPING_USD_MMBTU, "regas_usd_mmbtu": lc.REGAS_USD_MMBTU, "mmbtu_per_mwh": lc.MMBTU_PER_MWH, "max_quote_age_days": lc.MAX_QUOTE_AGE_DAYS},
                           read="Margin = netback minus FOB cost. A month is shown only when its TTF quote and the EUR/USD quote were both available at the cutoff and traded within the age limit.",
                           caveat="TTF and EUR/USD are delayed, unofficial quotes. Shipping and regasification are labelled assumptions, and deferred TTF months can go days without trading, in which case no netback is shown. JKM has no free futures source, so it is pending a collector, never estimated."),
        "lng_supply_risk": doc("LNG chokepoint route risk", "A source-provided route-risk score attached to maritime chokepoints on the LNG map. It is a qualitative risk attribute, not a measured disruption, a live freight rate or a probability of outage.",
                               "source risk score by chokepoint, grouped into high / elevated / low bands",
                               read="Gold arcs are modeled route context. Red, amber and teal rings mark chokepoints; hover or focus a ring for its source and interpretation.",
                               caveat="Coordinates and straight map segments are schematic, not surveyed shipping lanes. The score is not a point-in-time market observation and does not imply that a chokepoint is closed."),
        "lng_global": doc("Global LNG forward pricing model", "An integrated model that calculates all 20 LNG metrics for 24 monthly delivery periods. Observed point-in-time quotes anchor available months; missing inputs are estimated with calibrated fundamentals, facility marginal-cost stacks, engineering voyage economics, comparable-market relationships and correlated scenario simulation.",
                          "marginal FOB = minimum available-facility cost at regional demand; netback = (destination price x delivered energy - voyage cost - regas - loading) / loaded energy; bands = P10/P50/P90 of simulated scenarios",
                          {"delivery_months": lg.DELIVERY_COUNT, "model_version": lg.MODEL_VERSION},
                           read="Gold cells are direct observed anchors; dashed gold cells are observed TTF quotes converted from EUR/MWh with a labeled EUR/USD source. Every other cell is a modeled estimate, and each tooltip lists the quote lineage, freshness status, scenario band and provenance. A quote is accepted only when its available timestamp is at or before the cutoff and its age passes a series-specific freshness limit.",
                           caveat="Estimates are not tradeable quotes. Only quotes with a usable available timestamp and a series-specific freshness check can anchor a month; rejected quotes and their reasons are listed in the API. Facility costs, charter rates, boil-off, canal availability, basis and seasonal parameters are labeled assumptions or calibrated from the named PIT series in the parameter provenance; the full set and backtest result are in the model diagnostics drilldown."),

        "lng_global_point": doc("Modeled LNG calculation for one delivery month", "One of the 20 global LNG calculations for a single monthly delivery period, with observed anchor, low/base/high scenarios and model confidence.",
                                 "P10 / P50 / P90 from correlated scenario simulation", read="Hover or focus the cell for the scenario distribution, the observed-status label, the quote lineage and the modeling diagnostics behind the value.",
                                 caveat="Observed anchors are point-in-time gated and freshness checked; converted TTF anchors retain their EUR/MWh native value and state whether EUR/USD was observed or modeled. All modeled inputs are deterministic for a given model version, calibration vintage and seed."),

        # ---- fundamentals
        "shale_total": doc("Shale gas, six basins", "Sum of the monthly-average production of the six roster basins (Appalachia, Permian, Haynesville, Eagle Ford, Bakken, DJ).", "sum of the six basin series (Bcf/d)",
                           caveat="Shown only when all six are present; it is a sum of six basins, not total U.S. production."),
        "storage_total": doc("Working gas in storage", "Sum of the six EIA weekly storage regions for the same report week.", "sum of East, Midwest, Mountain, Pacific, South Central Salt and Non-Salt (Bcf)",
                             caveat="Shown only when all six regions are present for the same week."),
        "hdd_anomaly": doc("HDD vs 30-year normal", "Actual population-weighted heating degree days for the contiguous U.S. minus the 30-year normal for the same date.", "actual HDD - 30-year normal HDD",
                           read="Positive means colder than normal (more heating demand).", caveat="Heating degree days are derived here from NOAA data (provenance: extracted estimate)."),
        "flow_meters": doc("Live flow meters", "Pipeline and LNG feedgas meters with a measured daily volume.", "count of roster flow and LNG-feedgas agents that have a measured value",
                           caveat="No collector exists yet for these daily volumes, so the count is 0. Official monthly EIA volumes for the same LNG terminals and border crossings are collected and shown in their own panels, but they are monthly totals (MMcf per month), not daily meters. Arcs on the map are schematic links, not surveyed pipelines."),
        "lng_exports": doc("LNG exports by terminal (monthly)", "Total LNG exported from each U.S. terminal in a calendar month, all destinations, as published by EIA.", "EIA series ...-Z00 (monthly total exports); stored as published, MMcf per month",
                           read="This is exports, not the gas delivered to the terminal: terminals also burn fuel and lose gas, so feedgas is somewhat higher.",
                           caveat="Published about two months after the month ends, so the latest value is for a month that is already over."),
        "border_flows": doc("Pipeline volumes at border points (monthly)", "Natural gas moving by pipeline across a U.S. border point in a calendar month, as published by EIA: imports from Canada at Eastport (Kingsgate), Noyes (Emerson) and Waddington, and exports to Mexico at Rio Grande and Brownsville.",
                            "EIA border-point series; stored as published, MMcf per month",
                            caveat="Rio Grande and Brownsville are the nearest published crossings to the NET Mexico and Valley Crossing corridors; that mapping is an inference. Published about two months after the month ends."),
        "notices": doc("Critical notices", "Operator informational postings from Kinder Morgan interstate pipelines, shown as published.", "count of notices with a posting time in the last 7 days"),
        "force_majeure": doc("Force majeure", "Notices in the last 30 days that contain the phrase FORCE MAJEURE.", "count of matching notices in the last 30 days"),
        "alert": doc("Alert", "A message derived from the data above; the level is watch (something to look at), info (context) or gap (a data coverage limit)."),
        # ---- lineage vocabulary
        "t_target": doc("Observation (target) date", "The period the value describes, for example the trading day or storage week."),
        "t_published": doc("Published", "When the source says it published the value, if it states one."),
        "t_retrieved": doc("Retrieved", "When this system fetched the value from the source."),
        "t_available": doc("Available (point in time)", "The earliest moment this system could have used the value. Queries for an earlier cutoff cannot see it, which prevents look-ahead.",
                           "a row is eligible only if available <= the cutoff"),
        "provenance": doc("Provenance", "How the figure came to be.", read="measured: published by the source and stored unchanged. extracted estimate: derived here from measured rows. unverified seed: an old demo row, excluded from every calculation. pending collector: no collector yet, so no value is shown."),
        "quality": doc("Quality", "The collector's label for how far the value was checked.", read="validated: checked against the source schema. delayed quote unverified: a delayed, unofficial quote. validated approximation: a documented approximate method (for example population-weighted weather)."),
        "payload_hash": doc("Raw payload hash", "SHA-256 of the exact bytes fetched from the source. If 'payload archived' is shown, the original response is stored and can be re-read.", "sha256(raw response bytes)"),
        "pending": doc("Pending collector", "No collector writes this series yet. The dashboard shows no value rather than simulating one."),
        "timeframe": doc("Timeframe", "How many sessions the technical charts show. All three use daily closes; there is no intraday feed.", read="Seasonal swing 252 sessions; Intraday / short-term 60; Multi-year hedging 1260."),
        "roster": doc("Roster agents", "Every data series the platform is designed to collect, each with its intended source. Collected = has a measured or estimated value; pending = no collector yet."),
        "pit_rows": doc("Point-in-time rows", "Rows in the market database, each stamped with when it became available."),
        "kg_node": doc("Knowledge object", "A durable summary or source document stored in the vector knowledge library, with the time it became available and where it came from."),
    }
    formulas = {
        "hh_forward": "observed Henry Hub quote at the delivery month, otherwise base + seasonal amplitude with mean reversion",
        "terminal_feedgas": "HH + terminal basis + terminal tariff + fuel share x HH",
        "usgc_fob": "terminal feedgas x feed factor + liquefaction fee + loading cost",
        "atlantic_fob": "cost of the lowest-cost available Atlantic facility that clears regional demand after outages",
        "pacific_fob": "cost of the lowest-cost available Pacific facility that clears regional demand after outages",
        "spark30s_atlantic_freight": "(charter x voyage days + fuel tons x days x fuel price + canal toll + port charge x cargo) / delivered energy",
        "spark25s_pacific_freight": "(charter x voyage days + fuel tons x days x fuel price + canal toll + port charge x cargo) / delivered energy on the selected Pacific route",
        "usgc_ttf_netback": "(TTF at arrival month x delivered energy - voyage cost - regas x delivered energy - loading x cargo) / loaded cargo energy",
        "usgc_jkm_netback": "(JKM at arrival month x delivered energy - voyage cost - regas x delivered energy - loading x cargo) / loaded cargo energy",
        "panama_cape_spread": "Panama netback - Cape netback, per MMBtu of loaded cargo",
        "jkm_forward": "TTF + JKM basis + Asia winter premium + basis shock",
        "ttf_forward": f"TTF(EUR/MWh) x EURUSD / {lg.MMBTU_PER_MWH:g}, anchored to PIT quotes where available",
        "nwe_des": "TTF + northwest Europe regas fee + regional basis shock",
        "swe_des": "TTF + southwest Europe basis + regional basis shock",
        "nbp_forward": "TTF + NBP basis + regional basis shock",
        "wim_forward": "JKM - west India marker discount - regional basis shock",
        "jkm_ttf_spread": "JKM - TTF - 0.55 x Pacific freight - 0.18 x absolute basis shock",
        "winter_summer_spread": "mean of rolling winter-minus-summer spreads across Henry Hub, TTF, JKM and NBP",
        "m1_m2_calendar_spread": "mean of M1-minus-M2 spreads across Henry Hub, TTF, JKM and NBP",
        "brent_linked_parity": "(WTI-derived Brent proxy + labelled WTI-to-Brent premium) x Brent slope + constant",
    }
    for key, label, unit in lg.CALCULATIONS:
        out[f"lng_{key}"] = doc(
            label,
            f"One of the 20 Global LNG Forward Pricing calculations. {label} is modeled for every delivery month M1-M24; PIT quotes anchor the months where they exist.",
            formulas[key],
            {"unit": unit, "model_version": lg.MODEL_VERSION},
            read="The M1 card shows the P10-P90 range; the matrix shows P50 for M1-M24. Hover or focus a cell for its observed-status label, native quote value and unit, P25/P75, 95% interval, confidence, lineage and diagnostics.",
            caveat=("TTF is collected in EUR/MWh and converted to USD/MMBtu with EUR/USD; the tooltip states whether FX was observed or modeled. "
                    if key == "ttf_forward" else "")
                   + "Brent parity is a labelled WTI-plus-premium proxy when no Brent quote is collected. Modeled values are estimates, not observed market prices. Facility costs, freight, boil-off, basis, demand and seasonal parameters are explicit calibrated assumptions where observations are unavailable; provenance and vintage are in the API payload.",
        )
    return out
