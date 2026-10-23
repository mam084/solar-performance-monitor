"""Site configuration: load the fleet definition from config/sites.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "sites.yaml"
DATA_DIR = REPO_ROOT / "data"

CANONICAL_COLUMNS = ("ac_power", "poa_irradiance", "module_temp", "ambient_temp", "wind_speed")


@dataclass
class Site:
    system_id: int
    name: str
    location: str
    source: str  # "prize" or "basic"
    latitude: float
    longitude: float
    elevation_m: float
    timezone: str
    dc_capacity_kw: float
    mount: str  # "fixed" or "single_axis"
    tilt: float
    azimuth: float
    years_available: list[int]
    columns: dict[str, str | None] = field(default_factory=dict)
    # Raw units for columns that aren't SI, e.g. {"ambient_temp": "F", "wind_speed": "mph"}
    units: dict[str, str] = field(default_factory=dict)
    # Whether a raw timestamp marks the start or the end of its averaging interval
    timestamps: str = "start"
    # Filename substrings of files logged in UTC rather than local time
    utc_files: list[str] = field(default_factory=list)
    # Filename substring -> hours to add to that file's timestamps (fixed clock errors)
    file_offsets_h: dict[str, float] = field(default_factory=dict)
    # Inverter AC output limit (kW); inferred from the data's clipping ceiling if unset
    ac_capacity_kw: float | None = None

    @property
    def raw_dir(self) -> Path:
        return DATA_DIR / "raw" / str(self.system_id)

    @property
    def mapped_columns(self) -> dict[str, str]:
        """Canonical name -> raw column, for the columns that have been mapped."""
        return {k: v for k, v in self.columns.items() if v}


def load_sites(path: Path = CONFIG_PATH) -> dict[int, Site]:
    with open(path) as f:
        raw = yaml.safe_load(f)["sites"]
    sites = {}
    for sid, cfg in raw.items():
        cfg = dict(cfg)
        cols = cfg.pop("columns", None) or {}
        units = cfg.pop("units", None) or {}
        utc = cfg.pop("utc_files", None) or []
        offsets = cfg.pop("file_offsets_h", None) or {}
        sites[int(sid)] = Site(system_id=int(sid), columns=cols, units=units, utc_files=utc,
                               file_offsets_h=offsets, **cfg)
    return sites


def get_site(system_id: int) -> Site:
    sites = load_sites()
    if system_id not in sites:
        raise KeyError(f"System {system_id} is not in {CONFIG_PATH.name}. Known: {sorted(sites)}")
    return sites[system_id]
