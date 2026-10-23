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

# Converters from raw units to the units the model expects (°C, m/s, kW, W/m²)
UNIT_CONVERSIONS = {
    "F": lambda x: (x - 32.0) * 5.0 / 9.0,
    "mph": lambda x: x * 0.44704,
    "km/h": lambda x: x / 3.6,
    "W": lambda x: x / 1000.0,
}
# Other names the timestamp column goes by in some PVDAQ exports, in order of preference.
TIME_CANDIDATES = ("measured_on", "timestamp", "datetime", "date_time", "time", "local_time",
                   "utc_measured_on", "timestamp_utc", "date")


def find_time_col(columns) -> str:
    """Pick the timestamp column, case-insensitively. Raises with the header if none is found."""
    lower = {str(c).strip().lower(): c for c in columns}
    for name in TIME_CANDIDATES:
        if name in lower:
            return lower[name]
    for key, orig in lower.items():  # fall back to anything that looks like a time column
        if any(w in key for w in ("measured", "time", "date")):
            return orig
    raise KeyError(f"no timestamp column found; columns are: {list(columns)[:15]}")


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
    tcol = find_time_col(df.columns)
    if {"metric_id", "value"} <= set(df.columns):
        df = df.pivot_table(index=tcol, columns="metric_id", values="value", aggfunc="mean")
        df.columns = [f"metric_{c}" for c in df.columns]
    else:
        df = df.set_index(tcol)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def peek(site: Site, nrows: int = 2000) -> dict[Path, pd.DataFrame | Exception]:
    """First rows of each file. Cheap way to see which sensors a site has.

    A file that can't be parsed maps to the exception instead of stopping the whole peek.
    """
    files = raw_files(site)
    # Basic sites have one file per day; one sample day is enough to see the columns.
    if site.source == "basic" and files:
        files = files[len(files) // 2 : len(files) // 2 + 1]
    out = {}
    for p in files:
        try:
            out[p] = _to_wide(_read(p, nrows=nrows))
        except Exception as e:  # noqa: BLE001 - report and keep going
            out[p] = e
    return out


def load_site(site: Site, columns: dict[str, str | list[str]] | None = None,
              freq: str | None = "15min", timestamps: str | None = None) -> pd.DataFrame:
    """Load a site's data with canonical column names, on a regular `freq` time grid.

    `columns` maps canonical names to raw column names (defaults to the mapping in
    sites.yaml). A list of raw columns is combined: summed for ac_power (e.g. several
    inverters), averaged for everything else (e.g. several irradiance sensors).

    Files often use different intervals (e.g. 1-min irradiance, 15-min meter), so each
    file is averaged onto the `freq` grid before merging. Averaging power over an
    interval keeps energy correct. Pass freq=None to keep raw timestamps.

    Files listed under `utc_files` in sites.yaml are converted from UTC to the site's
    local clock first.

    If the site's raw timestamps mark the END of each interval (`timestamps: end` in
    sites.yaml, or the `timestamps` argument), each file is shifted back by its own
    interval first, so a 15-min meter reading stamped 00:15 lands in the 00:00 bin
    alongside the irradiance measured over the same minutes.

    Columns listed under `units` in sites.yaml are converted to °C, m/s and kW.
    """
    timestamps = timestamps or site.timestamps
    columns = columns or site.mapped_columns
    if not columns:
        raise ValueError(
            f"No columns mapped for site {site.system_id}. "
            f"Run `python -m solarmon.inspect {site.system_id}` and fill in config/sites.yaml."
        )
    wanted = {c for v in columns.values() for c in ([v] if isinstance(v, str) else v)}

    frames = [f for path in raw_files(site)
              if not (f := load_file(site, path, wanted, timestamps)).empty]
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

    for name, unit in site.units.items():
        if name in out:
            if unit not in UNIT_CONVERSIONS:
                raise ValueError(f"Unknown unit {unit!r} for {name}; known: {sorted(UNIT_CONVERSIONS)}")
            out[name] = UNIT_CONVERSIONS[unit](out[name])

    if "ac_power" in out:
        explicit = "ac_power" in site.units
        out["ac_power_kw"] = out.pop("ac_power") if explicit else to_kw(out["ac_power"], site.dc_capacity_kw)
        out = out.drop(columns="ac_power", errors="ignore")
    return out


def load_file(site: Site, path: Path, wanted: set[str], timestamps: str | None = None) -> pd.DataFrame:
    """One raw file's wanted columns, on the site's local clock with interval-start stamps.

    Applies, in order: UTC -> local conversion for files listed under `utc_files`
    (DST-aware), then the interval-end shift if `timestamps` is "end".
    Returns an empty frame if the file has none of the wanted columns.
    """
    timestamps = timestamps or site.timestamps
    head = _read(path, nrows=1).columns
    if {"metric_id", "value"} <= set(head):
        f = _to_wide(_read(path)).filter(items=wanted)
    else:
        cols = [c for c in head if c in wanted]
        if not cols:
            return pd.DataFrame()
        f = _to_wide(_read(path, columns=[find_time_col(head), *cols]))
    if f.empty:
        return f
    if is_utc_file(site, path):
        local = f.index.tz_localize("UTC").tz_convert(site.timezone).tz_localize(None)
        f = f.set_axis(local)
        f = f[~f.index.duplicated()]  # the repeated hour when clocks fall back
    if timestamps == "end":
        f = f.set_axis(f.index - _step(f))
    return f


def is_utc_file(site: Site, path: Path) -> bool:
    return any(s in path.name for s in site.utc_files)


def _step(df: pd.DataFrame) -> pd.Timedelta:
    """A file's typical sampling interval (ignores gaps like nights or outages)."""
    d = df.index.to_series().diff().dropna()
    return d.mode().iloc[0] if len(d) else pd.Timedelta(0)


def to_kw(power: pd.Series, dc_capacity_kw: float) -> pd.Series:
    """PVDAQ sites report power in W or kW. Infer which from the site's nameplate."""
    p99 = power.quantile(0.99)
    if p99 > 5 * dc_capacity_kw:  # far above nameplate in kW -> must be watts
        return power / 1000.0
    return power
