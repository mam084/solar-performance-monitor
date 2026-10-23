"""Read downloaded raw files into a single time-indexed DataFrame per site.

PVDAQ files are "wide": a `measured_on` timestamp column plus one column per sensor
(e.g. `poa_irradiance_o_149574`). A few older exports are "long"
(`measured_on, metric_id, value`); those get pivoted to wide.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Site

TIME_COL = "measured_on"


def raw_files(site: Site) -> list[Path]:
    """Data files for a site (metadata files excluded)."""
    files = [p for p in site.raw_dir.rglob("*") if p.suffix in (".csv", ".parquet")]
    return sorted(p for p in files if "metadata" not in p.parts)


def _read(path: Path, columns: list[str] | None = None, nrows: int | None = None) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path, columns=columns)
        return df.head(nrows) if nrows else df
    return pd.read_csv(path, usecols=columns, nrows=nrows)


def _to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise one file to wide format indexed by timestamp."""
    if {"metric_id", "value"} <= set(df.columns):
        df = df.pivot_table(index=TIME_COL, columns="metric_id", values="value", aggfunc="mean")
        df.columns = [f"metric_{c}" for c in df.columns]
    else:
        df = df.set_index(TIME_COL)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def peek(site: Site, nrows: int = 2000) -> dict[Path, pd.DataFrame]:
    """First rows of each file. Cheap way to see which sensors a site has."""
    files = raw_files(site)
    # Basic sites have one file per day; one sample day is enough to see the columns.
    if site.source == "basic" and files:
        files = files[len(files) // 2 : len(files) // 2 + 1]
    return {p: _to_wide(_read(p, nrows=nrows)) for p in files}


def load_site(site: Site, columns: dict[str, str | list[str]] | None = None,
              freq: str | None = "15min") -> pd.DataFrame:
    """Load a site's data with canonical column names, on a regular `freq` time grid.

    `columns` maps canonical names to raw column names (defaults to the mapping in
    sites.yaml). A list of raw columns is combined: summed for ac_power (e.g. several
    inverters), averaged for everything else (e.g. several irradiance sensors).

    Files often use different intervals (e.g. 1-min irradiance, 15-min meter), so each
    file is averaged onto the `freq` grid before merging. Averaging power over an
    interval keeps energy correct. Pass freq=None to keep raw timestamps.
    """
    columns = columns or site.mapped_columns
    if not columns:
        raise ValueError(
            f"No columns mapped for site {site.system_id}. "
            f"Run `python -m solarmon.inspect {site.system_id}` and fill in config/sites.yaml."
        )
    wanted = {c for v in columns.values() for c in ([v] if isinstance(v, str) else v)}

    frames = []
    for path in raw_files(site):
        head = _read(path, nrows=1).columns
        if {"metric_id", "value"} <= set(head):
            frames.append(_to_wide(_read(path)).filter(items=wanted))
            continue
        cols = [c for c in head if c in wanted]
        if cols:
            frames.append(_to_wide(_read(path, columns=[TIME_COL, *cols])))
    if freq:
        # Each frame is binned to the grid, labelled by interval start.
        frames = [f.resample(freq).mean() for f in frames]
    if not frames:
        raise ValueError(f"None of {sorted(wanted)} found in {site.raw_dir}")

    # Files can overlap (e.g. a full-history file plus a per-year file); first non-null value wins.
    raw = pd.concat(frames, axis=0).groupby(level=0).first()

    out = pd.DataFrame(index=raw.index)
    for name, src in columns.items():
        src = [src] if isinstance(src, str) else list(src)
        present = [c for c in src if c in raw.columns]
        if not present:
            continue
        block = raw[present]
        out[name] = block.sum(axis=1, min_count=1) if name == "ac_power" else block.mean(axis=1)

    if "ac_power" in out:
        out["ac_power_kw"] = to_kw(out.pop("ac_power"), site.dc_capacity_kw)
    return out


def to_kw(power: pd.Series, dc_capacity_kw: float) -> pd.Series:
    """PVDAQ sites report power in W or kW. Infer which from the site's nameplate."""
    p99 = power.quantile(0.99)
    if p99 > 5 * dc_capacity_kw:  # far above nameplate in kW -> must be watts
        return power / 1000.0
    return power
