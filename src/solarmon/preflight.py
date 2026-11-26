"""Preflight: check a site's raw data before the first real pipeline build.

Runs every check that has bitten this project so far and says what to change in
config/sites.yaml when one fails, so the first real run ends in a list of fixes
rather than a confusing number.

    1. raw files        downloaded at all? which years?
    2. column mapping   every mapped column present in at least one file?
    3. file clocks      each file's daily curve peaks near solar noon? (UTC / offset files)
    4. coverage         share of daylight intervals with power and irradiance, per year
    5. alignment        best power-vs-irradiance lag, per year and season
    6. calibration      scale factor in a plausible range, nRMSE on healthy days < 5%

Usage:
    python -m solarmon.preflight 2107
"""

from __future__ import annotations

import argparse
import warnings
from dataclasses import dataclass

import pandas as pd

from .config import Site, get_site
from .load import load_site, raw_files

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def run(site: Site) -> tuple[list[Check], pd.DataFrame | None]:
    """All checks in order. Stops early only when later checks can't run."""
    checks: list[Check] = []
    files = raw_files(site)
    if not files:
        checks.append(Check("raw files", FAIL, f"no data files in {site.raw_dir}",
                            f"python -m solarmon.ingest download {site.system_id} "
                            "--include meter irradiance environment"))
        return checks, None
    mb = sum(p.stat().st_size for p in files) / 1e6
    checks.append(Check("raw files", PASS, f"{len(files)} files, {mb:,.0f} MB"))

    # 2. mapping
    mapped = site.mapped_columns
    missing_req = [c for c in ("ac_power", "poa_irradiance") if c not in mapped]
    if missing_req:
        checks.append(Check("column mapping", FAIL, f"{', '.join(missing_req)} not mapped",
                            f"python -m solarmon.inspect {site.system_id}, then fill `columns:` in sites.yaml"))
        return checks, None
    present = set()
    for p in files:
        try:
            head = pd.read_parquet(p).columns if p.suffix == ".parquet" else pd.read_csv(p, nrows=0).columns
        except Exception:  # noqa: BLE001 - unreadable files show up in inspect
            continue
        present.update(head)
    wanted = {name: ([v] if isinstance(v, str) else list(v)) for name, v in mapped.items()}
    absent = {name: [c for c in cols if c not in present] for name, cols in wanted.items()}
    absent = {k: v for k, v in absent.items() if v}
    if absent:
        checks.append(Check("column mapping", FAIL if any(k in absent for k in ("ac_power", "poa_irradiance")) else WARN,
                            "not found in any file: " + "; ".join(f"{k} -> {v}" for k, v in absent.items()),
                            "correct the names in sites.yaml (python -m solarmon.inspect lists them)"))
        if any(k in absent for k in ("ac_power", "poa_irradiance")):
            return checks, None
    else:
        temp = "module_temp" if "module_temp" in mapped else ("ambient_temp" if "ambient_temp" in mapped else None)
        checks.append(Check("column mapping", PASS if temp else WARN,
                            f"{len(mapped)} signals mapped" + ("" if temp else "; no temperature, model assumes 25 °C"),
                            "" if temp else "map ambient_temp (or module_temp) for a better model"))

    # 3. file clocks
    from .qa import file_timing
    try:
        timing = file_timing(site)
        bad = timing[timing["looks_right"] == "CHECK"].reset_index()
        bad = bad[bad["signal"].isin(["ac_power", "poa_irradiance"])]
        if bad.empty:
            checks.append(Check("file clocks", PASS, f"{len(timing)} file/signal pairs peak near solar noon"))
        for r in bad.itertuples():
            off = r.offset_h
            stem = r.file.rsplit(".", 1)[0]
            if 6 <= abs(off) <= 9:
                fix = f"looks like UTC: add `{stem}` to utc_files"
            else:
                fix = f"add `{stem}: {-round(off * 4) / 4}` under file_offsets_h (confirm with qa.lag_scan by month)"
            checks.append(Check("file clocks", WARN, f"{r.file} ({r.signal}) peaks {off:+.2f} h from solar noon", fix))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("file clocks", WARN, f"could not run: {e}"))

    # 4. coverage
    from .qa import clean
    df = clean(load_site(site), site)
    day = df["poa_irradiance"] > 50
    cov = pd.DataFrame({
        "power": df["ac_power_kw"].notna()[day].groupby(df.index[day].year).mean(),
        "irradiance": df["poa_irradiance"].notna().groupby(df.index.year).mean(),
    }).round(2)
    thin = cov[(cov["power"] < 0.8)]
    detail = ", ".join(f"{y}: {r.power:.0%} power" for y, r in cov.iterrows())
    checks.append(Check("coverage", WARN if len(thin) else PASS, detail,
                        f"years with < 80% power coverage ({', '.join(map(str, thin.index))}) will show many data gaps"
                        if len(thin) else ""))

    # 5. alignment
    from .qa import lag_scan
    try:
        lags = lag_scan(df, max_hours=4, by="year")
        off = lags[lags["best_lag_h"].abs() > 0.25]
        checks.append(Check("alignment", WARN if len(off) else PASS,
                            "best lag 0 h in every year" if off.empty else
                            "off in " + ", ".join(f"{y} ({r.best_lag_h:+.2f} h)" for y, r in off.iterrows()),
                            "" if off.empty else "run qa.lag_scan(df, by='month') to pin down when the offset starts"))
    except Exception as e:  # noqa: BLE001
        checks.append(Check("alignment", WARN, f"could not run: {e}"))

    # 6. calibration + accuracy
    from .detect import detect_events
    from .expected import model_site, rmse_pct
    from .qa import trim_to_sensor_start
    from .metrics import daily_performance
    import contextlib
    import io
    with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        out = model_site(trim_to_sensor_start(df), site)  # scale warning is reported below instead
    scale = out.attrs["scale"]
    checks.append(Check("calibration", PASS if 0.75 <= scale <= 1.05 else WARN,
                        f"scale {scale:.3f} on {out.attrs['reference'][0][:10]} to {out.attrs['reference'][1][:10]}, "
                        f"AC limit {out.attrs['ac_capacity_kw']:.0f} kW",
                        "" if 0.75 <= scale <= 1.05 else
                        "unusual: check power units, the POA column, or dc_capacity_kw; "
                        "or pick a healthier window with --reference"))
    _, d = detect_events(out, daily_performance(out), site.system_id, single_axis=site.mount == "single_axis")
    healthy = pd.Series(out.index.normalize().isin(d.index[d["flag"] == "ok"]), index=out.index)
    nrmse = rmse_pct(out["ac_power_kw"], out["expected_ac_kw"], out["poa_irradiance"], only=healthy)
    by_year = {y: rmse_pct(g["ac_power_kw"], g["expected_ac_kw"], g["poa_irradiance"], only=healthy.loc[g.index])
               for y, g in out.groupby(out.index.year) if healthy.loc[g.index].any()}
    by_year = {y: v for y, v in by_year.items() if pd.notna(v)}
    worst = max(by_year, key=by_year.get) if by_year else None
    checks.append(Check("accuracy", PASS if nrmse < 5 else WARN,
                        f"nRMSE on healthy days {nrmse:.1f}% (target < 5%)"
                        + (f"; worst year {worst}: {by_year[worst]:.1f}%" if worst else ""),
                        "" if nrmse < 5 else
                        f"a single bad year usually means a clock or sensor problem in that year's files"))
    return checks, cov


def report(site: Site, checks: list[Check]) -> str:
    icon = {PASS: "✓", WARN: "!", FAIL: "✗"}
    lines = [f"Preflight for {site.system_id} {site.name}"]
    for c in checks:
        lines.append(f"  [{icon[c.status]}] {c.name:<15} {c.detail}")
        if c.fix:
            lines.append(f"      -> {c.fix}")
    if any(c.name == "file clocks" and c.status == WARN for c in checks):
        lines.append("Fix the file clocks first: alignment, calibration and accuracy all follow from them.")
    worst = FAIL if any(c.status == FAIL for c in checks) else WARN if any(c.status == WARN for c in checks) else PASS
    lines.append({PASS: f"Ready: python -m solarmon.pipeline build {site.system_id}",
                  WARN: f"Buildable, but review the warnings first: python -m solarmon.pipeline build {site.system_id}",
                  FAIL: "Not ready: fix the failures above."}[worst])
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("system_id", type=int)
    args = p.parse_args(argv)
    site = get_site(args.system_id)
    checks, _ = run(site)
    print(report(site, checks))


if __name__ == "__main__":
    main()
