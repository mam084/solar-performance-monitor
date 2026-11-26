"""End-to-end daily run: raw data -> expected output -> PI -> events -> draft tickets.

Writes everything the app needs to data/processed/<id>/, small enough to commit:

    intraday.parquet   15-min actual, expected, irradiance, temperature
    daily.parquet      daily PI, baseline, flags, event labels
    events.json        detected events with evidence
    tickets.json       a draft ticket per event (status: pending_review)
    meta.json          site info, calibration, model accuracy, data source

Usage:
    python -m solarmon.pipeline build 2107            # real PVDAQ data in data/raw/2107
    python -m solarmon.pipeline build 2107 --demo     # synthetic data with injected faults
    python -m solarmon.pipeline build all --demo      # every site in sites.yaml
    python -m solarmon.pipeline build 2107 --claude   # draft tickets with Claude (needs ANTHROPIC_API_KEY)
    python -m solarmon.pipeline build 2107 --reference 2018-03-01 2019-02-28
"""

from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config
from .config import Site, get_site
from .detect import DEFAULT_PRICE_USD_KWH, backtest, detect_events, false_alarms
from .expected import model_site, rmse_pct
from .metrics import daily_performance
from .tickets import draft_ticket


TICKET_WINDOW_DAYS = 45  # events that ended longer ago than this are filed as history


def processed_dir(system_id: int) -> Path:
    return config.DATA_DIR / "processed" / str(system_id)


def site_dict(site: Site) -> dict:
    return {k: getattr(site, k) for k in ("system_id", "name", "location", "latitude", "longitude",
                                          "timezone", "dc_capacity_kw", "mount", "tilt", "azimuth")}


def build(system_id: int, demo: bool = False, reference: slice | None = None,
          use_claude: bool = False, out_dir: Path | None = None, verbose: bool = True,
          preflight: list[dict] | None = None) -> dict:
    site = get_site(system_id)
    truth = None
    if demo:
        from .demo import make_demo
        raw, faults = make_demo(site)
        truth = pd.DataFrame([f.__dict__ for f in faults])
        source = "demo"
    else:
        from .load import load_site
        from .qa import clean, trim_to_sensor_start
        raw = trim_to_sensor_start(clean(load_site(site), site))
        source = "pvdaq"

    out = model_site(raw, site, reference=reference)
    daily = daily_performance(out)
    events, d = detect_events(out, daily, site.system_id, price_usd_kwh=DEFAULT_PRICE_USD_KWH,
                              single_axis=site.mount == "single_axis")

    # Honest model error: productive intervals on days with no event
    healthy_days = d.index[(d["flag"] == "ok")]
    healthy = pd.Series(out.index.normalize().isin(healthy_days), index=out.index)
    nrmse_healthy = rmse_pct(out["ac_power_kw"], out["expected_ac_kw"], out["poa_irradiance"], only=healthy)

    sd = site_dict(site)
    event_dicts = [e.to_dict() for e in events]
    # Only recent or ongoing events need someone to act; older ones are history
    cutoff = out.index.max().normalize() - pd.Timedelta(days=TICKET_WINDOW_DAYS)
    tickets = []
    for e in event_dicts:
        recent = e["active"] or pd.Timestamp(e["end"]) >= cutoff
        t = draft_ticket(e, sd, use_claude=use_claude and recent)
        if not recent:
            t["status"] = "historical"
        tickets.append(t)

    meta = {
        "site": sd,
        "source": source,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_start": str(out.index.min().date()),
        "data_end": str(out.index.max().date()),
        "calibration_scale": round(out.attrs["scale"], 4),
        "ac_capacity_kw": round(out.attrs["ac_capacity_kw"], 1),
        "reference_window": out.attrs["reference"],
        "trimmed_before": raw.attrs.get("trimmed_before"),
        "shape_correction_range": ([round(min(out.attrs["shape_table"].values()), 3),
                                    round(max(out.attrs["shape_table"].values()), 3)]
                                   if out.attrs.get("shape_table") else None),
        "nrmse_healthy_pct": round(nrmse_healthy, 2),
        "price_usd_kwh": DEFAULT_PRICE_USD_KWH,
        "n_events": len(events),
        "ticket_window_days": TICKET_WINDOW_DAYS,
    }
    if preflight is not None:
        meta["preflight"] = preflight
    if truth is not None:
        bt = backtest(events, truth)
        meta["backtest"] = {
            "faults_injected": len(bt),
            "detected": int(bt["detected"].sum()),
            "correct_kind": int(bt["correct_kind"].sum()),
            "false_alarms": len(false_alarms(events, truth)),
            "median_delay_days": float(bt["delay_days"].median()),
            "rows": json.loads(bt.to_json(orient="records")),
        }

    dest = out_dir or processed_dir(site.system_id)
    dest.mkdir(parents=True, exist_ok=True)
    intraday = out[["ac_power_kw", "expected_ac_kw", "poa_irradiance", "ambient_temp"]].astype("float32")
    intraday.to_parquet(dest / "intraday.parquet", compression="zstd")
    keep = ["actual_kwh", "expected_kwh", "pi", "poa_kwh_m2", "data_gap", "actual_kwh_day",
            "expected_kwh_day", "baseline_pi", "dev", "flag", "event_kind"]
    d[keep].to_parquet(dest / "daily.parquet", compression="zstd")
    _dump(dest / "events.json", event_dicts)
    _dump(dest / "tickets.json", tickets)
    _dump(dest / "meta.json", meta)
    if truth is not None:
        truth.to_csv(dest / "injected_faults.csv", index=False)

    if verbose:
        print(f"[{site.system_id}] {site.name} ({source}): {meta['data_start']} to {meta['data_end']}")
        print(f"  scale {meta['calibration_scale']:.3f}, AC limit {meta['ac_capacity_kw']:.0f} kW, "
              f"nRMSE on healthy days {meta['nrmse_healthy_pct']:.1f}%")
        for e in events:
            print(f"  {e.start} to {e.end}  {e.label:<26} {e.severity:<8} "
                  f"{e.energy_lost_kwh:>9,.0f} kWh{'  ACTIVE' if e.active else ''}")
        if "backtest" in meta:
            b = meta["backtest"]
            print(f"  backtest: {b['detected']}/{b['faults_injected']} found, {b['correct_kind']} labelled "
                  f"correctly, {b['false_alarms']} false alarms")
        print(f"  wrote {dest}")
    return meta


def _dump(path: Path, obj) -> None:
    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        return str(o)
    path.write_text(json.dumps(obj, indent=2, default=default) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="run the pipeline for one site")
    b.add_argument("system_id", help="a system id, or 'all'")
    b.add_argument("--demo", action="store_true", help="use synthetic data with injected faults")
    b.add_argument("--claude", action="store_true", help="draft tickets with Claude")
    b.add_argument("--reference", nargs=2, metavar=("START", "END"), help="known-good calibration window")
    args = p.parse_args(argv)
    ref = slice(*args.reference) if args.reference else None
    ids = sorted(config.load_sites()) if args.system_id == "all" else [int(args.system_id)]
    for sid in ids:
        build(sid, demo=args.demo, reference=ref, use_claude=args.claude)


if __name__ == "__main__":
    main()
