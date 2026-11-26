"""The ML layer is used only when it beats physics on data it never saw."""

import numpy as np
import pandas as pd

from solarmon.config import get_site
from solarmon.demo import make_demo
from solarmon.detect import detect_events
from solarmon.expected import model_site
from solarmon.metrics import daily_performance
from solarmon.ml import residual_model


def _run(df, site):
    out = model_site(df, site)
    _, d = detect_events(out, daily_performance(out), site.system_id)
    return residual_model(out, site, d.index[d["flag"] == "ok"])


def test_not_adopted_when_physics_already_explains_the_data():
    site = get_site(2107)
    df, _ = make_demo(site, faults=[], seed=11)
    pred, report = _run(df, site)
    assert pred is None and not report["adopted"]
    assert report["holdout_nrmse_ml"] >= report["holdout_nrmse_physics"] * 0.97


def test_adopted_when_there_is_a_pattern_physics_misses():
    """Weak-light losses the model doesn't know about: depends on irradiance level, not time
    of day, so the month x half-hour shape table can't absorb it."""
    site = get_site(2107)
    df, _ = make_demo(site, faults=[], seed=11)
    poa = df["poa_irradiance"]
    df["ac_power_kw"] *= 0.75 + 0.25 * np.clip(poa / 700, 0, 1)
    pred, report = _run(df, site)
    assert report["adopted"], report
    assert report["holdout_nrmse_ml"] < 0.9 * report["holdout_nrmse_physics"]
    assert isinstance(pred, pd.Series) and pred.notna().mean() > 0.9
