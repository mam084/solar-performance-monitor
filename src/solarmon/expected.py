"""Expected AC output from measured weather: the physics baseline.

Uses NREL's PVWatts model (via pvlib) driven by the site's own plane-of-array
irradiance sensor. Because POA is measured in the array plane, no sky-model
transposition is needed. This works the same for fixed-tilt and tracking arrays.

The DC estimate is then calibrated with a single scale factor fit on a
"known-good" reference window, and passed through the inverter (efficiency curve
plus the AC output limit). That factor absorbs things the metadata doesn't
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


def dc_power_kw(df: pd.DataFrame, site: Site) -> pd.Series:
    """Uncalibrated PVWatts DC power (kW) from POA irradiance and cell temperature."""
    poa = df["poa_irradiance"].clip(lower=0)
    dc = pvlib.pvsystem.pvwatts_dc(poa, cell_temperature(df), pdc0=site.dc_capacity_kw * 1000.0,
                                   gamma_pdc=GAMMA_PDC)
    return (dc / 1000.0).rename("model_dc_kw")


def inverter_ac_kw(dc_kw: pd.Series, ac_capacity_kw: float, clip: bool = True) -> pd.Series:
    """PVWatts inverter: part-load efficiency curve, then (optionally) the AC output limit."""
    pdc0 = ac_capacity_kw / INVERTER_EFF
    zeta = (dc_kw / pdc0).where(dc_kw > 0)
    eta = INVERTER_EFF / 0.9637 * (-0.0162 * zeta - 0.0059 / zeta + 0.9858)
    ac = (dc_kw * eta).clip(lower=0).fillna(0).where(dc_kw.notna())
    return ac.clip(upper=ac_capacity_kw) if clip else ac


def ac_capacity(df: pd.DataFrame, site: Site) -> float:
    """Inverter AC limit (kW): from sites.yaml, else the observed clipping ceiling."""
    if site.ac_capacity_kw:
        return float(site.ac_capacity_kw)
    observed = df["ac_power_kw"].quantile(0.999)
    return float(observed) if observed > 0 else site.dc_capacity_kw / DC_AC_RATIO


def pvwatts_ac_kw(df: pd.DataFrame, site: Site) -> pd.Series:
    """Uncalibrated PVWatts AC estimate (kW), with an inverter sized at DC/1.2."""
    ac_cap = site.ac_capacity_kw or site.dc_capacity_kw / DC_AC_RATIO
    return inverter_ac_kw(dc_power_kw(df, site), ac_cap).rename("pvwatts_ac_kw")


def fit_scale(actual_kw: pd.Series, model_kw: pd.Series, poa: pd.Series,
              ac_cap: float | None = None) -> float:
    """Least-squares scale factor (through the origin) on clear, productive periods.

    Points at or near the inverter limit are excluded: when the inverter clips,
    output no longer depends on how healthy the array is, so they'd bias the fit.
    Robust two-pass: the second pass drops points far from the first fit, so a few
    outage hours in the reference window don't drag it.
    """
    mask = (poa > MIN_POA_FOR_FIT) & actual_kw.notna() & model_kw.notna() & (model_kw > 0)
    if ac_cap:
        mask &= (actual_kw < 0.95 * ac_cap)
    a, m = actual_kw[mask], model_kw[mask]
    if len(a) < 50:
        raise ValueError(f"Only {len(a)} usable points in reference window; pick a longer one.")
    k = float((a * m).sum() / (m * m).sum())
    resid = (a - k * m) / (k * m)
    keep = resid.abs() < 3 * resid.abs().median() + 1e-9
    a, m = a[keep], m[keep]
    return float((a * m).sum() / (m * m).sum())


def expected_ac_kw(df: pd.DataFrame, site: Site, reference: slice | None = None,
                   reference_days: int = 365) -> pd.DataFrame:
    """Add `expected_ac_kw` to a site frame. `reference` is a time slice of known-good data.

    The calibration factor scales the array's DC output *before* the inverter, so
    the inverter's AC limit (the flat ceiling on sunny days) stays where it really is.

    If no reference is given, the first `reference_days` after power and every model
    input (irradiance, temperature) exist are used. A full year averages out seasonal
    effects (sun angle, temperature) that a short window would bake into the baseline.
    Returns a copy with model_dc_kw, expected_ac_kw, and attrs scale / ac_capacity_kw / reference.
    """
    out = df.copy()
    out["model_dc_kw"] = dc_power_kw(out, site)
    ac_cap = ac_capacity(out, site)
    unclipped = inverter_ac_kw(out["model_dc_kw"], ac_cap, clip=False)
    if reference is None:
        # Every model input must exist (irradiance AND temperature), not just power + POA
        usable = ((out["poa_irradiance"] > MIN_POA_FOR_FIT) & out["ac_power_kw"].notna()
                  & (out["model_dc_kw"] > 0))
        if not usable.any():
            raise ValueError("No periods where power, irradiance and temperature all exist; "
                             "check the column mapping.")
        start = usable.idxmax()  # first usable timestamp
        reference = slice(start, start + pd.Timedelta(days=reference_days))
    ref = out.loc[reference]
    scale = fit_scale(ref["ac_power_kw"], unclipped.loc[ref.index], ref["poa_irradiance"], ac_cap)
    out["expected_ac_kw"] = inverter_ac_kw(out["model_dc_kw"] * scale, ac_cap)
    out.attrs.update(scale=scale, ac_capacity_kw=ac_cap,
                     reference=(str(ref.index.min()), str(ref.index.max())))
    if not 0.5 < scale < 1.3:
        print(f"warning: calibration scale {scale:.2f} is unusual. Check power units, "
              f"the POA column choice, or dc_capacity_kw for site {site.system_id}.")
    return out


def rmse_pct(actual: pd.Series, expected: pd.Series, poa: pd.Series,
             only: pd.Series | None = None) -> float:
    """Normalised RMSE on productive periods, as % of mean expected output.

    `only` is an optional boolean mask, e.g. to score the model on healthy days only
    (outages are real events, not model error).
    """
    mask = (poa > MIN_POA_FOR_FIT) & actual.notna() & expected.notna()
    if only is not None:
        mask &= only.reindex(mask.index, fill_value=False)
    err = actual[mask] - expected[mask]
    return float(np.sqrt((err**2).mean()) / expected[mask].mean() * 100)
