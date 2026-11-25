"""Calibrate and benchmark the integrated LNG model with memory-bounded CPU batches.

 Reads the point-in-time market database read-only and writes only runtime calibration artifacts. CPU batches use bounded multiprocessing; the optional
 GPU backend uses visible device 0 only so the existing Ollama process on GPU 1 is preserved. No production service, database row, or repository
 configuration is modified.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(BASE_DIR))
import lng_global as lg

DEFAULT_DB = BASE_DIR / "henry_hub_pit.db"
RUNTIME = BASE_DIR / "runtime"
FINAL_FILE = RUNTIME / "lng_global_calibration.json"
PARTIAL_FILE = RUNTIME / "lng_global_calibration.partial.json"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _meminfo() -> dict:
    out = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        parts = rest.strip().split()
        if parts:
            out[key] = int(parts[0]) * 1024
    total = out.get("MemTotal", 1)
    avail = out.get("MemAvailable", 0)
    stotal = out.get("SwapTotal", 0)
    sfree = out.get("SwapFree", 0)
    return {"mem_total_gb": round(total / 2**30, 2), "mem_available_gb": round(avail / 2**30, 2),
            "swap_total_gb": round(stotal / 2**30, 2), "swap_used_gb": round((stotal - sfree) / 2**30, 2)}


def _environment(use_gpu: bool = False) -> dict:
    mem = _meminfo()
    disk = shutil.disk_usage(BASE_DIR)
    accelerator = "CPU NumPy/SciPy OpenBLAS"
    if use_gpu:
        try:
            import torch
            accelerator = {"backend": "cuda:0", "torch": torch.__version__, "cuda": torch.version.cuda,
                           "device": torch.cuda.get_device_name(0), "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2)}
        except (ImportError, AssertionError, RuntimeError) as exc:
            accelerator = {"backend": "unavailable", "error": str(exc)}
    return {"repository": str(BASE_DIR), "python": os.sys.executable, "cpu_logical": os.cpu_count() or 1,
            "memory": mem, "disk_free_gb": round(disk.free / 2**30, 2),
            "accelerator": accelerator, "numpy": np.__version__}


def _backup_existing(path: Path) -> str | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.stem}.pre_provenance_{int(time.time())}.json")
    shutil.copy2(path, target)
    return str(target)


def _read_series(conn: sqlite3.Connection, agent: str, cutoff: str, years: int = 12) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT p.target_timestamp, p.value FROM pit_market_data p WHERE p.agent_id=? AND p.value IS NOT NULL AND p.available_timestamp<=? "
        "AND COALESCE(p.provenance,'measured')='measured' AND COALESCE(p.quality_status,'')<>'unverified_seed' "
        "AND p.source_id IS NOT NULL AND p.source_id<>'' "
        "AND p.available_timestamp=(SELECT MAX(q.available_timestamp) FROM pit_market_data q WHERE q.agent_id=p.agent_id "
        "AND q.target_timestamp=p.target_timestamp AND q.available_timestamp<=? AND COALESCE(q.provenance,'measured')='measured' "
        "AND COALESCE(q.quality_status,'')<>'unverified_seed' AND q.source_id IS NOT NULL AND q.source_id<>'') "
        "ORDER BY p.target_timestamp DESC LIMIT ?", (agent, cutoff, cutoff, years * 400)).fetchall()
    return [(str(ts), float(v)) for ts, v in rows if ts and str(ts)[:4].isdigit()]


def _read_ttf_series(conn: sqlite3.Connection, cutoff: str, months: list[str]) -> list[dict]:
    rows = conn.execute(
        "SELECT p.agent_id,p.target_timestamp,p.available_timestamp,p.value,p.unit,p.source_id,p.quality_status,p.provenance,p.published_timestamp,p.raw_payload_hash "
        "FROM pit_market_data p WHERE p.agent_id LIKE 'Agent_TTF_%' AND p.value IS NOT NULL AND p.available_timestamp<=? "
        "AND COALESCE(p.provenance,'measured')='measured' AND COALESCE(p.quality_status,'')<>'unverified_seed' "
        "AND p.source_id IS NOT NULL AND p.source_id<>'' "
        "AND p.available_timestamp=(SELECT MAX(q.available_timestamp) FROM pit_market_data q WHERE q.agent_id=p.agent_id "
        "AND q.target_timestamp=p.target_timestamp AND q.available_timestamp<=? AND COALESCE(q.provenance,'measured')='measured' "
        "AND COALESCE(q.quality_status,'')<>'unverified_seed' AND q.source_id IS NOT NULL AND q.source_id<>'') "
        "ORDER BY p.target_timestamp DESC,p.agent_id", (cutoff, cutoff)).fetchall()
    out = []
    for agent, target, available, value, unit, source, quality, provenance, published, payload in rows:
        month = agent.replace("Agent_TTF_", "").replace("_", "-")
        if len(month) != 7 or month not in months or any(existing["month"] == month for existing in out):
            continue
        out.append({"agent_id": agent, "month": month, "target_timestamp": str(target), "available_timestamp": str(available),
                    "value": float(value), "unit": unit, "source_id": source, "quality_status": quality,
                    "provenance": provenance or "measured", "published_timestamp": published, "raw_payload_hash": payload})
    return out


def _series_lineage(conn: sqlite3.Connection, cutoff: str) -> dict:
    rows = conn.execute(
        "SELECT agent_id,COUNT(*),MIN(target_timestamp),MAX(target_timestamp),MIN(available_timestamp),MAX(available_timestamp),"
        "GROUP_CONCAT(DISTINCT source_id),GROUP_CONCAT(DISTINCT quality_status) FROM pit_market_data "
        "WHERE available_timestamp<=? AND COALESCE(provenance,'measured')='measured' AND COALESCE(quality_status,'')<>'unverified_seed' "
        "AND source_id IS NOT NULL AND source_id<>'' GROUP BY agent_id", (cutoff,)).fetchall()
    return {row[0]: {"rows": row[1], "target_range": [row[2], row[3]], "available_range": [row[4], row[5]],
                     "source_ids": sorted([x for x in (row[6] or "").split(",") if x]),
                     "quality_statuses": sorted([x for x in (row[7] or "").split(",") if x])} for row in rows}


def _seasonal_fit(rows: list[tuple[str, float]]) -> dict:
    if len(rows) < 24:
        return {}
    y = np.array([v for _, v in rows], dtype=float)
    theta = np.array([2 * math.pi * (int(ts[5:7]) - 1) / 12.0 for ts, _ in rows], dtype=float)
    x = np.column_stack([np.ones(len(y)), np.cos(theta), np.sin(theta)])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    amp = float(math.hypot(coef[1], coef[2]))
    phase = float(math.atan2(-coef[2], coef[1]))
    target = x @ coef
    best_mr, best_err = 0.10, float("inf")
    for mr in np.linspace(0.01, 0.40, 40):
        pred = np.empty_like(y)
        pred[0] = target[0]
        for i in range(1, len(y)):
            pred[i] = pred[i - 1] + mr * (target[i] - pred[i - 1])
        err = float(np.mean((y - pred) ** 2))
        if err < best_err:
            best_mr, best_err = float(mr), err
    resid = y - target
    return {"hh_base": float(coef[0]), "hh_season_amp": amp, "hh_phase": phase, "hh_mean_reversion": best_mr,
            "hh_vol": float(np.std(resid) / max(np.mean(y), 1e-9)), "seasonal_fit_rmse": math.sqrt(best_err), "observations": len(y)}


def _backtest(rows: list[tuple[str, float]], seasonal: dict) -> dict:
    if len(rows) < 36:
        return {}
    series = sorted(rows)
    y = np.array([v for _, v in series], dtype=float)
    months = np.array([int(ts[5:7]) for ts, _ in series], dtype=int)
    start = max(24, len(y) - 120)
    seasonal_pred, mr_pred, ridge_pred, actual = [], [], [], []
    mr = seasonal.get("hh_mean_reversion", 0.10)
    target = seasonal.get("hh_base", float(np.mean(y))) + seasonal.get("hh_season_amp", 0.5) * np.cos(
        2 * math.pi * (months - 1) / 12.0 + seasonal.get("hh_phase", 0.0))
    for i in range(start, len(y) - 1):
        historical = y[:i + 1]
        mhist = months[:i + 1]
        seasonal_pred.append(historical[np.where(mhist == months[i + 1])[0][-1]])
        prev = mr_pred[-1] if mr_pred else historical[-1]
        nxt = target[i + 1]
        mr_pred.append(prev + mr * (nxt - prev))
        xh = np.column_stack([np.ones(len(mhist)), np.cos(2 * math.pi * (mhist - 1) / 12.0), np.sin(2 * math.pi * (mhist - 1) / 12.0)])
        coef, *_ = np.linalg.lstsq(xh, historical, rcond=None)
        theta = 2 * math.pi * (months[i + 1] - 1) / 12.0
        ridge_pred.append(coef[0] + coef[1] * math.cos(theta) + coef[2] * math.sin(theta))
        actual.append(y[i + 1])
    truth = np.array(actual)
    scores = {}
    for name, pred in (("seasonal_naive", seasonal_pred), ("mean_reverting", mr_pred), ("ridge_seasonal", ridge_pred)):
        err = truth - np.array(pred)
        scores[name] = {"rmse": round(float(np.sqrt(np.mean(err**2))), 6), "mae": round(float(np.mean(np.abs(err))), 6)}
    winner = min(scores, key=lambda k: scores[k]["rmse"])
    scores["selected"] = winner
    return scores


def _batch_worker(args: dict) -> dict:
    params = args["params"]
    months = args["months"]
    result = lg.simulate(params, months, args["hh_observed"], args["ttf_observed"], args["fx"], args["oil"], args["n"], args["seed"], args.get("backend", "cpu"))
    quantiles = {}
    for key, array in result["arrays"].items():
        quantiles[key] = np.quantile(array, [0.025, 0.10, 0.50, 0.90, 0.975], axis=0).tolist()
    return {"quantiles": quantiles, "diagnostics": result["diagnostics"]}


def _safe_resources(workers: int, batch: int) -> tuple[int, int]:
    mem = _meminfo()
    avail = mem["mem_available_gb"]
    swap_used = mem["swap_used_gb"]
    if avail < 1.0 or swap_used > 1.5:
        return 1, min(batch, 1024)
    if avail < 3.0:
        return 1, min(batch, 4096)
    return max(1, min(workers, os.cpu_count() or 1, 4)), max(512, min(batch, 8192))


def _aggregate_partials(partials: list[dict], weights: list[int]) -> dict:
    out = {}
    for key in partials[0]["quantiles"]:
        values = np.array([p["quantiles"][key] for p in partials], dtype=float)
        w = np.array(weights, dtype=float)[:, None, None]
        out[key] = np.sum(values * w, axis=0) / w.sum()
    return out


def _parameter_provenance(params: dict, seasonal: dict, backtest: dict, hh_rows: list, oil_rows: list, ttf_rows: list,
                          fx_rows: list, lineage: dict) -> dict:
    out = {key: {"value": value, "source": "labelled_assumption", "reason": "hard-coded default; no calibrated observation supplied"}
           for key, value in params.items()}
    hh_meta = lineage.get("Agent_HH_M1", {})
    for key in ("hh_base", "hh_season_amp", "hh_phase", "hh_mean_reversion", "hh_vol"):
        if key in seasonal and key in out:
            out[key] = {"value": seasonal[key], "source": "calibrated_from_pit_series", "agent_id": "Agent_HH_M1",
                        "method": "seasonal least squares and residual volatility" if key != "hh_mean_reversion" else "grid search over mean-reversion coefficients",
                        "observations": seasonal.get("observations"), "target_range": hh_meta.get("target_range"),
                        "available_range": hh_meta.get("available_range"), "source_ids": hh_meta.get("source_ids"),
                        "quality_statuses": hh_meta.get("quality_statuses"), "seasonal_fit_rmse": seasonal.get("seasonal_fit_rmse")}
    meta = lineage.get("Agent_Crude_WTI_Spot", {})
    if oil_rows:
        for key, method in (("oil_base", "mean of latest 36 PIT WTI observations"), ("oil_vol", "standard deviation of latest 252 PIT WTI observations divided by oil_base")):
            out[key] = {"value": params[key], "source": "calibrated_from_pit_series", "agent_id": "Agent_Crude_WTI_Spot", "method": method,
                        "observations": len(oil_rows), "target_range": meta.get("target_range"), "available_range": meta.get("available_range"),
                        "source_ids": meta.get("source_ids"), "quality_statuses": meta.get("quality_statuses")}
    meta = lineage.get("Agent_FX_EURUSD", {})
    if fx_rows:
        out["fx_base"] = {"value": params["fx_base"], "source": "calibrated_from_pit_series", "agent_id": "Agent_FX_EURUSD",
                         "method": "mean of latest 10 PIT EUR/USD observations", "observations": len(fx_rows),
                         "target_range": meta.get("target_range"), "available_range": meta.get("available_range"),
                         "source_ids": meta.get("source_ids"), "quality_statuses": meta.get("quality_statuses")}
    if ttf_rows:
        out["ttf_base_eur_mwh"] = {"value": params["ttf_base_eur_mwh"], "source": "calibrated_from_pit_series",
                                    "agent_ids": [row["agent_id"] for row in ttf_rows], "method": "mean of eligible PIT TTF month quotes",
                                    "observations": len(ttf_rows), "months": [row["month"] for row in ttf_rows],
                                    "source_ids": sorted({row["source_id"] for row in ttf_rows if row["source_id"]}),
                                    "quality_statuses": sorted({row["quality_status"] for row in ttf_rows if row["quality_status"]})}
    if backtest.get("selected") in ("seasonal_naive", "ridge_seasonal"):
        out["hh_mean_reversion"] = {**out["hh_mean_reversion"], "value": params["hh_mean_reversion"], "source": "model_selection_adjustment",
                                    "method": f"backtest winner {backtest['selected']} added 0.02 to the fitted coefficient, capped at 0.35"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=50000)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cutoff", default=None)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--gpu", action="store_true", help="use the precompiled CUDA PyTorch backend on visible GPU 0")
    args = ap.parse_args()
    if args.gpu:
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    cutoff = args.cutoff or _utc()
    env = _environment(args.gpu)
    if args.gpu:
        try:
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA unavailable")
        except (ImportError, AssertionError, RuntimeError) as exc:
            raise SystemExit(f"GPU backend unavailable: {exc}")
    months = lg._month_sequence(cutoff)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        hh_rows = _read_series(conn, "Agent_HH_M1", cutoff)
        oil_rows = _read_series(conn, "Agent_Crude_WTI_Spot", cutoff)
        fx_rows = _read_series(conn, "Agent_FX_EURUSD", cutoff)
        ttf_rows = _read_ttf_series(conn, cutoff, months)
        lineage = _series_lineage(conn, cutoff)
    finally:
        conn.close()
    seasonal = _seasonal_fit(hh_rows)
    backtest = _backtest(hh_rows, seasonal)
    params = dict(lg.PARAM_DEFAULTS)
    for key in ("hh_base", "hh_season_amp", "hh_phase", "hh_mean_reversion", "hh_vol"):
        if key in seasonal:
            params[key] = seasonal[key]
    if oil_rows:
        params["oil_base"] = float(np.mean([v for _, v in oil_rows[-36:]]))
        params["oil_vol"] = float(np.std([v for _, v in oil_rows[-252:]]) / max(params["oil_base"], 1.0))
    if ttf_rows:
        params["ttf_base_eur_mwh"] = float(np.mean([row["value"] for row in ttf_rows]))
    if fx_rows:
        params["fx_base"] = float(np.mean([v for _, v in fx_rows[-10:]]))
    if backtest.get("selected") in ("seasonal_naive", "ridge_seasonal"):
        params["hh_mean_reversion"] = min(0.35, params["hh_mean_reversion"] + 0.02)
    parameter_provenance = _parameter_provenance(params, seasonal, backtest, hh_rows, oil_rows, ttf_rows, fx_rows, lineage)

    hh_observed = {}
    ttf_observed = {}
    fx = None
    oil = None
    if hh_rows:
        hh_observed[months[0]] = hh_rows[0][1]
    for row in ttf_rows:
        ttf_observed[row["month"]] = row["value"]
    if fx_rows:
        fx = fx_rows[0][1]
    if oil_rows:
        oil = oil_rows[0][1]

    workers, batch = _safe_resources(args.workers, args.batch)
    backend = "gpu" if args.gpu else "cpu"
    if args.gpu:
        workers = 1
        batch = max(50000, min(int(args.batch), 250000))
    total = max(batch, int(args.scenarios))
    jobs = []
    seed_start = 20261120
    seed = seed_start
    remaining = total
    while remaining > 0:
        n = min(batch, remaining)
        jobs.append({"params": params, "months": months, "hh_observed": hh_observed, "ttf_observed": ttf_observed,
                     "fx": fx, "oil": oil, "n": n, "seed": seed, "backend": backend})
        seed += 1
        remaining -= n

    partial_backup = _backup_existing(PARTIAL_FILE)
    started = time.perf_counter()
    partials, weights, batch_times, diagnostics = [], [], [], {}
    use_pool = backend == "cpu" and workers > 1 and len(jobs) > 1
    if use_pool:
        executor = ProcessPoolExecutor(max_workers=workers)
        futures = {executor.submit(_batch_worker, job): job["n"] for job in jobs}
        try:
            for future in as_completed(futures):
                n = futures[future]
                result = future.result()
                partials.append(result)
                weights.append(n)
                diagnostics = result["diagnostics"]
                checkpoint = {"available_timestamp": _utc(), "status": "partial", "completed_scenarios": sum(weights), "total_scenarios": total}
                PARTIAL_FILE.write_text(json.dumps(checkpoint, indent=2, sort_keys=True))
                batch_times.append(round(time.perf_counter() - started, 4))
        finally:
            executor.shutdown(wait=True, cancel_futures=False)
    else:
        for job in jobs:
            t0 = time.perf_counter()
            result = _batch_worker(job)
            partials.append(result)
            weights.append(job["n"])
            diagnostics = result["diagnostics"]
            batch_times.append(round(time.perf_counter() - t0, 4))
            PARTIAL_FILE.write_text(json.dumps({"available_timestamp": _utc(), "status": "partial", "completed_scenarios": sum(weights), "total_scenarios": total}, indent=2, sort_keys=True))
    elapsed = time.perf_counter() - started
    aggregated = _aggregate_partials(partials, weights)
    diagnostics = dict(diagnostics)
    diagnostics["scenario_count"] = int(sum(weights))
    diagnostics["seed"] = seed_start
    diagnostics["seed_range"] = [seed_start, seed - 1]
    diagnostics["batch_count"] = len(jobs)
    diagnostics["aggregated_batch_diagnostics"] = True
    benchmark = {"elapsed_seconds": round(elapsed, 4), "scenarios": int(sum(weights)), "scenarios_per_second": round(sum(weights) / max(elapsed, 1e-9), 1),
                  "backend": backend, "device_name": diagnostics.get("device_name"), "batch_size": batch, "workers": workers, "batch_times_seconds": batch_times,
                  "environment": env, "seed": seed_start, "seed_range": [seed_start, seed - 1], "batch_count": len(jobs),
                 "memory_after": _meminfo(), "peak_rss_mb": round(float(__import__("resource").getrusage(__import__("resource").RUSAGE_SELF).ru_maxrss) / 1024, 1),
                 "batch_summaries": {k: {"p10": [round(float(v), 4) for v in values[1]], "p50": [round(float(v), 4) for v in values[2]],
                                         "p90": [round(float(v), 4) for v in values[3]]} for k, values in aggregated.items()}}
    final_backup = _backup_existing(FINAL_FILE)
    doc = {"model_version": lg.MODEL_VERSION, "available_timestamp": _utc(), "cutoff": cutoff, "status": "complete",
           "params": params, "parameter_provenance": parameter_provenance, "seasonal_fit": seasonal, "backtest": backtest,
           "scenario_count": int(sum(weights)), "seed": seed_start, "benchmark": benchmark, "diagnostics": diagnostics,
           "pit_filter": {"available_at_or_before_cutoff": True, "unverified_seed_excluded": True, "measured_provenance_required": True,
                          "source_id_required": True, "latest_vintage_per_target": True},
           "input_lineage": {"hh": lineage.get("Agent_HH_M1", {}), "oil": lineage.get("Agent_Crude_WTI_Spot", {}),
                             "fx": lineage.get("Agent_FX_EURUSD", {}), "ttf": ttf_rows},
           "artifact_backups": {"final": final_backup, "partial": partial_backup}}
    FINAL_FILE.write_text(json.dumps(doc, indent=2, sort_keys=True))
    print(json.dumps({"final_file": str(FINAL_FILE), "backup": final_backup, "scenarios": sum(weights), "seconds": benchmark["elapsed_seconds"],
                      "scenarios_per_second": benchmark["scenarios_per_second"], "backend": backend, "device": diagnostics.get("device_name"),
                      "workers": workers, "batch": batch, "backtest": backtest.get("selected"), "memory": _meminfo()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
