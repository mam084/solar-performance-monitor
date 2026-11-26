"""Model error on full-health days vs chronic shortfall: model problems vs plant problems."""

import numpy as np

from solarmon.config import get_site
from solarmon.demo import make_demo
from solarmon.detect import detect_events
from solarmon.expected import model_site
from solarmon.health import assess
from solarmon.metrics import daily_performance


def _assess(df, site):
    out = model_site(df, site)
    _, d = detect_events(out, daily_performance(out), site.system_id)
    return assess(out, d, 0.12)


def test_healthy_site_has_little_shortfall():
    site = get_site(2107)
    df, _ = make_demo(site, faults=[], seed=5)
    h = _assess(df, site)
    assert h["nrmse_full_health_pct"] < 5
    assert h["chronic_shortfall_pct"] < 4


def test_scattered_small_losses_show_as_shortfall_not_model_error():
    """A plant that loses 3-7% on half of days at random: each too small to alert on
    (larger drops become events instead), but it adds up. The model error on full-health
    days should stay low."""
    site = get_site(2107)
    df, _ = make_demo(site, faults=[], seed=5)
    rng = np.random.default_rng(0)
    days = df.index.normalize().unique()
    hit = days[rng.random(len(days)) < 0.5]
    loss = dict(zip(hit, rng.uniform(0.03, 0.07, len(hit))))
    factor = df.index.normalize().map(lambda d: 1 - loss.get(d, 0.0)).to_numpy()
    base = _assess(df, site)
    df["ac_power_kw"] *= factor
    h = _assess(df, site)
    assert h["chronic_shortfall_pct"] > base["chronic_shortfall_pct"] + 1.5
    assert h["nrmse_full_health_pct"] < 5
