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


def _read_series(conn: sqlite3.Connection, agent: str, years: int = 12) -> list[tuple[str, float]]:
    rows = conn.execute("select target_timestamp, value from pit_market_data where agent_id=? and value is not null "
                        "and provenance!='unverified_seed' order by target_timestamp desc limit ?", (agent, years * 400)).fetchall()
    return [(str(ts), float(v)) for ts, v in rows if ts and str(ts)[:4].isdigit()]


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
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        hh_rows = _read_series(conn, "Agent_HH_M1")
        oil_rows = _read_series(conn, "Agent_Crude_WTI_Spot")
        ttf_rows = conn.execute("select agent_id, value from pit_market_data where agent_id like 'Agent_TTF_%' and value is not null "
                                "order by target_timestamp desc limit 24").fetchall()
        fx_rows = _read_series(conn, "Agent_FX_EURUSD")
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
        params["ttf_base_eur_mwh"] = float(np.mean([float(v) for _, v in ttf_rows]))
    if fx_rows:
        params["fx_base"] = float(np.mean([v for _, v in fx_rows[-10:]]))
    if backtest.get("selected") in ("seasonal_naive", "ridge_seasonal"):
        params["hh_mean_reversion"] = min(0.35, params["hh_mean_reversion"] + 0.02)

    months = lg._month_sequence(cutoff)
    hh_observed = {}
    ttf_observed = {}
    fx = None
    oil = None
    if hh_rows:
        hh_observed[months[0]] = hh_rows[0][1]
    for row in ttf_rows:
        m = row[0].replace("Agent_TTF_", "").replace("_", "-")
        if m in months and m not in ttf_observed:
            ttf_observed[m] = float(row[1])
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
    seed = 20261120
    remaining = total
    while remaining > 0:
        n = min(batch, remaining)
        jobs.append({"params": params, "months": months, "hh_observed": hh_observed, "ttf_observed": ttf_observed,
                     "fx": fx, "oil": oil, "n": n, "seed": seed, "backend": backend})
        seed += 1
        remaining -= n

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
    benchmark = {"elapsed_seconds": round(elapsed, 4), "scenarios": int(sum(weights)), "scenarios_per_second": round(sum(weights) / max(elapsed, 1e-9), 1),
                  "backend": backend, "device_name": diagnostics.get("device_name"), "batch_size": batch, "workers": workers, "batch_times_seconds": batch_times, "environment": env,
                 "memory_after": _meminfo(), "peak_rss_mb": round(float(__import__("resource").getrusage(__import__("resource").RUSAGE_SELF).ru_maxrss) / 1024, 1),
                 "batch_summaries": {k: {"p10": [round(float(v), 4) for v in values[1]], "p50": [round(float(v), 4) for v in values[2]],
                                         "p90": [round(float(v), 4) for v in values[3]]} for k, values in aggregated.items()}}
    doc = {"model_version": lg.MODEL_VERSION, "available_timestamp": _utc(), "cutoff": cutoff, "status": "complete",
           "params": params, "seasonal_fit": seasonal, "backtest": backtest, "scenario_count": int(sum(weights)),
           "seed": 20261120, "benchmark": benchmark, "diagnostics": diagnostics}
    FINAL_FILE.write_text(json.dumps(doc, indent=2, sort_keys=True))
    print(json.dumps({"final_file": str(FINAL_FILE), "scenarios": sum(weights), "seconds": benchmark["elapsed_seconds"],
                      "scenarios_per_second": benchmark["scenarios_per_second"], "backend": backend, "device": diagnostics.get("device_name"),
                      "workers": workers, "batch": batch, "backtest": backtest.get("selected"), "memory": _meminfo()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
