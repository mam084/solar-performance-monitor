"""Expected AC output from measured weather: the physics baseline.

Uses NREL's PVWatts model (via pvlib) driven by the site's own plane-of-array
irradiance sensor. Because POA is measured in the array plane, no sky-model
transposition is needed. This works the same for fixed-tilt and tracking arrays.

The raw PVWatts estimate is then calibrated with a single scale factor fit on a
"known-good" reference window. That factor absorbs things the metadata doesn't
tell us (wiring losses, mismatch, nameplate vs real module power), so the
baseline answers: "what would this site produce today if it were as healthy as
it was during the reference window?"
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from .config import Site

GAMMA_PDC = -0.004  # power temperature coefficient (1/°C), typical crystalline silicon
DC_AC_RATIO = 1.2  # assumed when inverter nameplate is unknown
INVERTER_EFF = 0.96
MIN_POA_FOR_FIT = 200  # W/m², ignore low-light periods when calibrating


def cell_temperature(df: pd.DataFrame) -> pd.Series:
    """Cell temp from the best available sensor.

    Back-of-module temp + small conduction delta (Sandia model) if we have it,
    otherwise estimate from ambient temp + wind with the Sandia open-rack model.
    """
    poa = df["poa_irradiance"].clip(lower=0)
    if "module_temp" in df and df["module_temp"].notna().mean() > 0.5:
        return df["module_temp"] + poa / 1000.0 * 3.0
    if "ambient_temp" in df:
        wind = df["wind_speed"].fillna(1.0) if "wind_speed" in df else 1.0
        p = pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"]["open_rack_glass_glass"]
        return pvlib.temperature.sapm_cell(poa, df["ambient_temp"], wind, **p)
    return pd.Series(25.0, index=df.index)  # no temperature data: assume STC


def pvwatts_ac_kw(df: pd.DataFrame, site: Site) -> pd.Series:
    """Uncalibrated PVWatts AC estimate (kW) from POA irradiance and temperature."""
    pdc0_w = site.dc_capacity_kw * 1000.0
    poa = df["poa_irradiance"].clip(lower=0)
    dc = pvlib.pvsystem.pvwatts_dc(poa, cell_temperature(df), pdc0=pdc0_w, gamma_pdc=GAMMA_PDC)
    inv_pdc0 = pdc0_w / DC_AC_RATIO / INVERTER_EFF
    ac = pvlib.inverter.pvwatts(dc, pdc0=inv_pdc0, eta_inv_nom=INVERTER_EFF)
    return (ac.clip(lower=0) / 1000.0).rename("pvwatts_ac_kw")


def fit_scale(actual_kw: pd.Series, model_kw: pd.Series, poa: pd.Series) -> float:
    """Least-squares scale factor (through the origin) on clear, productive periods.

    Uses a robust two-pass fit: the second pass drops points far from the first
    fit, so a few outage or clipping hours in the reference window don't drag it.
    """
    mask = (poa > MIN_POA_FOR_FIT) & actual_kw.notna() & model_kw.notna() & (model_kw > 0)
    a, m = actual_kw[mask], model_kw[mask]
    if len(a) < 50:
        raise ValueError(f"Only {len(a)} usable points in reference window; pick a longer one.")
    k = float((a * m).sum() / (m * m).sum())
    resid = (a - k * m) / (k * m)
    keep = resid.abs() < 3 * resid.abs().median() + 1e-9
    a, m = a[keep], m[keep]
    return float((a * m).sum() / (m * m).sum())


def expected_ac_kw(df: pd.DataFrame, site: Site, reference: slice | None = None) -> pd.DataFrame:
    """Add `expected_ac_kw` to a site frame. `reference` is a time slice of known-good data.

    If no reference is given, the first 60 days where power and every model input
    (irradiance, temperature) exist are used, since sensors often come online at
    different times.
    Returns a copy with columns: pvwatts_ac_kw, expected_ac_kw, and attrs['scale'].
    """
    out = df.copy()
    out["pvwatts_ac_kw"] = pvwatts_ac_kw(out, site)
    if reference is None:
        # Every model input must exist (irradiance AND temperature), not just power + POA
        usable = ((out["poa_irradiance"] > MIN_POA_FOR_FIT) & out["ac_power_kw"].notna()
                  & (out["pvwatts_ac_kw"] > 0))
        if not usable.any():
            raise ValueError("No periods where power, irradiance and temperature all exist; "
                             "check the column mapping.")
        start = usable.idxmax()  # first usable timestamp
        reference = slice(start, start + pd.Timedelta(days=60))
    ref = out.loc[reference]
    scale = fit_scale(ref["ac_power_kw"], ref["pvwatts_ac_kw"], ref["poa_irradiance"])
    out["expected_ac_kw"] = out["pvwatts_ac_kw"] * scale
    out.attrs["scale"] = scale
    out.attrs["reference"] = (str(ref.index.min()), str(ref.index.max()))
    if not 0.5 < scale < 1.3:
        print(f"warning: calibration scale {scale:.2f} is unusual. Check power units, "
              f"the POA column choice, or dc_capacity_kw for site {site.system_id}.")
    return out


def rmse_pct(actual: pd.Series, expected: pd.Series, poa: pd.Series) -> float:
    """Normalised RMSE on productive periods, as % of mean expected output."""
    mask = (poa > MIN_POA_FOR_FIT) & actual.notna() & expected.notna()
    err = actual[mask] - expected[mask]
    return float(np.sqrt((err**2).mean()) / expected[mask].mean() * 100)
