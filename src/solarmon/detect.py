"""Underperformance detection and event classification.

Works on the daily performance index (PI = actual / expected energy) plus the 15-min
frame it came from. Three steps:

1. **Baseline.** Each day is compared with what's normal *for this site lately*: the
   rolling median of recent PI, recomputed with flagged days left out so a long fault
   doesn't become the new normal. Its ratio to the baseline is `dev`. Thresholds are
   scaled to the site's own scatter (`site_thresholds`).
2. **Daily flags.** outage (dev < 0.15), low (dev < 0.93 on a quiet site), high (dev > 1.10, output
   beating physics means the irradiance sensor reads low), capped (a shortfall only in
   the high-output midday hours), data_gap (no meter data), no_irradiance (power but no POA). Very dark days are too noisy to judge and neither
   break nor extend an event.
3. **Events.** Runs of flagged days become events. Low runs are classified by shape:

   =================  =========================================================
   partial_outage     abrupt step down, flat afterwards (inverter, string, fuse)
   soiling            gradual slide, often reset by rain or a wash
   curtailment        normal in the morning/evening, capped at midday
                      (loss concentrated in high-output intervals)
   tracker_stall      the reverse: fine at midday, short in the morning and evening
                      (single-axis rows parked flat)
   =================  =========================================================

Each event carries the evidence a technician (or the ticket agent) needs: dates,
PI before/during, energy lost, estimated cost, and the shape features behind its label.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

OUTAGE_DEV = 0.15
LOW_DEV = 0.93
HIGH_DEV = 1.10
CAPPED_DEV = 0.97  # a capped day needs only a small shortfall: its shape is the tell
CAPPED_SHAPE_GAP = 0.12
PLATEAU_FRAC = 0.2   # share of high-output intervals pinned at the day's max with expected above it
CLEAR_DAY_VARIABILITY = 0.08  # mean 15-min irradiance change / daily peak; above this it's cloudy
MIN_DAYS = {"outage": 1, "low": 3, "high": 3, "capped": 2, "stalled": 2, "data_gap": 1, "no_irradiance": 2}
DARK_DAY_KWH_M2 = 1.0  # days with less sunlight than this are too noisy to judge
DEFAULT_PRICE_USD_KWH = 0.12

KIND_LABELS = {
    "outage": "Full outage",
    "partial_outage": "Partial outage",
    "soiling": "Soiling / gradual loss",
    "curtailment": "Curtailment / output cap",
    "sensor_fault": "Irradiance sensor fault",
    "tracker_stall": "Tracker stall",
    "snow": "Snow cover",
    "data_gap": "Monitoring data gap",
}


@dataclass
class Event:
    site_id: int
    kind: str
    start: str
    end: str
    days: int
    active: bool
    severity: str
    pi_before: float | None
    pi_during: float | None
    energy_lost_kwh: float
    est_cost_usd: float
    loss_pct: float | None
    evidence: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.site_id}-{self.start}-{self.kind}"

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, **asdict(self)}


# --------------------------------------------------------------------------- daily view

def daily_frame(out: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Daily table with everything the detector needs, on a continuous calendar.

    Adds full-day energy (all daylight, not just the >200 W/m² hours the PI uses),
    irradiance coverage, and the midday-vs-shoulder shape feature.
    """
    day = out.index.normalize()
    step_h = out.index.to_series().diff().median() / pd.Timedelta(hours=1)
    cap = float(out.attrs.get("ac_capacity_kw") or out["ac_power_kw"].quantile(0.999))
    producing = out["ac_power_kw"] > 0.02 * cap

    full = pd.DataFrame({
        "actual_kwh_day": out["ac_power_kw"].groupby(day).sum(min_count=1) * step_h,
        "expected_kwh_day": out["expected_ac_kw"].groupby(day).sum(min_count=1) * step_h,
        # Share of producing intervals that have an irradiance reading
        "poa_coverage": out["poa_irradiance"].notna()[producing].groupby(day[producing]).mean(),
        "producing_intervals": producing.groupby(day).sum(),
        "shape_gap": _shape_gap(out),
        "plateau_frac": _plateau_frac(out),
        "variability": _variability(out),
        "tmax": (out["ambient_temp"].groupby(day).max() if "ambient_temp" in out
                 else pd.Series(dtype=float)),
        "zero_frac": _zero_frac(out, cap),
    })
    cal = pd.date_range(day.min(), day.max(), freq="D")
    d = daily.reindex(cal).join(full.reindex(cal))
    d["poa_coverage"] = d["poa_coverage"].fillna(1.0)
    return d


def _zero_frac(out: pd.DataFrame, cap: float) -> pd.Series:
    """Share of sunny intervals (POA > 100 W/m²) where output is effectively zero."""
    day = out.index.normalize()
    sunny = out["poa_irradiance"] > 100
    off = (out["ac_power_kw"] <= 0.005 * cap) & out["ac_power_kw"].notna()
    return off[sunny].groupby(day[sunny]).mean()


SNOW_MONTHS = (10, 11, 12, 1, 2, 3, 4, 5)
SNOW_TMAX_C = 3.0      # a day this cold within two days before the event
SNOW_MAX_ZERO = 0.8    # covered panels still trickle some power; a tripped inverter makes none


def _looks_like_snow(d: pd.DataFrame, s, e) -> tuple[bool, dict]:
    """Snow: freezing weather just before, and low-but-not-zero output while the
    (cleaned or heated) irradiance sensor still sees sun."""
    if "tmax" not in d or s.month not in SNOW_MONTHS:
        return False, {}
    cold = d.loc[s - pd.Timedelta(days=2): s, "tmax"].min()
    zero = d.loc[s:e, "zero_frac"].mean()
    if pd.isna(cold) or pd.isna(zero):
        return False, {}
    return bool(cold <= SNOW_TMAX_C and zero < SNOW_MAX_ZERO), {"coldest_max_temp_c": _r(cold, 1),
                                                                 "zero_output_share": _r(zero, 2)}


def _variability(out: pd.DataFrame) -> pd.Series:
    """Mean 15-min change in irradiance as a share of the day's peak: low on clear days."""
    day = out.index.normalize()
    poa = out["poa_irradiance"]
    peak = poa.groupby(day).transform("max")
    return (poa.diff().abs() / peak).where(poa > 50).groupby(day).mean().rename("variability")


def _plateau_frac(out: pd.DataFrame) -> pd.Series:
    """Share of high-output intervals where output sits flat at the day's max while expected is higher.

    A curtailed or setpoint-limited site runs pinned at one level through midday. Clipping
    at the inverter's own limit doesn't count: the model already clips expected there.
    """
    day = out.index.normalize()
    exp, act = out["expected_ac_kw"], out["ac_power_kw"]
    peak_exp = exp.groupby(day).transform("max")
    day_max = act.groupby(day).transform("max")
    high = exp > 0.5 * peak_exp
    pinned = high & (act >= 0.97 * day_max) & (exp > 1.08 * act)
    below_limit = day_max < 0.95 * float(out.attrs.get("ac_capacity_kw") or act.quantile(0.999))
    return (pinned.groupby(day).sum() / high.groupby(day).sum().replace(0, np.nan)).where(
        below_limit.groupby(day).first()).rename("plateau_frac")


def _shape_gap(out: pd.DataFrame) -> pd.Series:
    """Per day: median actual/expected in low-output intervals minus in high-output ones.

    Near 0 when a loss scales the whole curve (a dead inverter, dirt). Large and
    positive when output is fine in the morning and evening but capped at midday.
    """
    exp = out["expected_ac_kw"]
    day = out.index.normalize()
    peak = exp.groupby(day).transform("max")
    ratio = (out["ac_power_kw"] / exp).where(exp > 0.05 * peak)
    lo = ratio.where((exp > 0.1 * peak) & (exp < 0.5 * peak)).groupby(day).median()
    hi = ratio.where(exp > 0.8 * peak).groupby(day).median()
    return (lo - hi).rename("shape_gap")


def site_thresholds(dev: pd.Series) -> tuple[float, float]:
    """Low / high alert thresholds scaled to how noisy this site's daily PI is.

    A quiet site keeps the defaults (alert below 0.93 or above 1.10 of baseline). A noisy
    one needs a bigger move before it alarms: 2.5 robust standard deviations. Site 2107's
    real data scatters about 8% day to day, so it alerts below roughly 0.80.
    """
    x = dev.dropna()
    if len(x) < 30:
        return LOW_DEV, HIGH_DEV
    sd = float((x - x.median()).abs().median() * 1.4826)
    return min(LOW_DEV, 1 - 2.5 * sd), max(HIGH_DEV, 1 + 2.5 * sd)


def add_baseline(d: pd.DataFrame, window_days: int = 90) -> pd.DataFrame:
    """Rolling baseline PI and each day's deviation from it, robust to long faults.

    The baseline is the rolling median of recent days that weren't flagged (a second pass
    re-fits without the first pass's flags), so a long fault never becomes the new normal.
    Thresholds come from the site's own scatter (`site_thresholds`) and are kept in
    `d.attrs`.
    """
    d = d.copy()
    pi = d["pi"]
    judged = d["poa_kwh_m2"].fillna(0) >= DARK_DAY_KWH_M2
    usable = pi.where(judged & pi.between(0.3, 1.5))
    mask = pd.Series(True, index=d.index)
    low, high = LOW_DEV, HIGH_DEV
    for _ in range(3):  # later passes ignore days the earlier pass flagged
        src = usable.where(mask)
        base = src.rolling(f"{window_days}D", min_periods=15).median().shift(1)
        # Before there's enough history, use the early-period level
        early = src.dropna().iloc[:60].median() if src.notna().any() else 1.0
        base = base.fillna(early).clip(0.6, 1.4)
        dev = pi / base
        low, high = site_thresholds(dev.where(judged & mask))
        mask = ~((dev < low) | (dev > high))
    d["baseline_pi"] = base
    d["dev"] = dev
    d["judged"] = judged
    d.attrs["thresholds"] = (round(low, 3), round(high, 3))
    return d


def flag_days(d: pd.DataFrame, single_axis: bool = False) -> pd.Series:
    """One flag per day: outage, low, high, data_gap, no_irradiance, dark, ok, or none."""
    f = pd.Series("ok", index=d.index, dtype=object)
    f[d["pi"].isna() & d["producing_intervals"].fillna(0).eq(0)] = "none"  # night-only / no data
    f[~d["judged"]] = "dark"
    low, high = d.attrs.get("thresholds", (LOW_DEV, HIGH_DEV))
    f[d["dev"] < low] = "low"
    f[d["dev"] > high] = "high"
    # Output capped at midday (fine morning and evening): only shows on sunny days
    clear = d["variability"] < CLEAR_DAY_VARIABILITY  # shape is only readable on clear days
    capped_dev = min(CAPPED_DEV, (1 + low) / 2)
    # A cap leaves two marks: a flat top, and a normal morning against a short midday
    capped = (d["plateau_frac"] > PLATEAU_FRAC) & (d["shape_gap"] > CAPPED_SHAPE_GAP)
    f[(d["dev"] < capped_dev) & capped & clear & d["judged"]] = "capped"
    # The reverse shape: short in the morning and evening, fine at midday (trackers parked flat)
    if single_axis:
        f[(d["dev"] < capped_dev) & (d["shape_gap"] < -CAPPED_SHAPE_GAP) & clear & d["judged"]] = "stalled"
    f[(d["dev"] < OUTAGE_DEV) & d["judged"]] = "outage"
    f[~d["judged"] & (d["dev"] < OUTAGE_DEV)] = "outage"  # zero output is zero on any day
    f[d["poa_coverage"] < 0.5] = "no_irradiance"
    f[d["data_gap"].fillna(False).astype(bool)] = "data_gap"
    return f


# --------------------------------------------------------------------------- events

def _runs(flags: pd.Series, kind: str, max_gap: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Consecutive runs of `kind`, bridging up to `max_gap` neutral days (dark/none/ok)."""
    runs, start, last, gap = [], None, None, 0
    neutral = {"dark", "none"}
    for day, f in flags.items():
        if f == kind:
            start = start or day
            last, gap = day, 0
        elif start is not None:
            gap += 1
            tolerate = f in neutral or (f == "ok" and kind in ("low", "high", "capped", "stalled"))
            if not tolerate or gap > max_gap:
                runs.append((start, last))
                start, gap = None, 0
    if start is not None:
        runs.append((start, last))
    return runs


def detect_events(out: pd.DataFrame, daily: pd.DataFrame, site_id: int,
                  price_usd_kwh: float = DEFAULT_PRICE_USD_KWH,
                  single_axis: bool = False) -> tuple[list[Event], pd.DataFrame]:
    """Find and classify events. Returns (events, the daily table with baseline and flags).

    `single_axis` allows tracker-stall events; on a fixed array that shape means something else.
    """
    d = add_baseline(daily_frame(out, daily))
    d["flag"] = flag_days(d, single_axis=single_axis)
    last_day = d.index[d["flag"] != "none"].max()

    events = []
    for flag, gap in (("outage", 0), ("low", 2), ("high", 2), ("capped", 3), ("stalled", 3), ("data_gap", 0),
                      ("no_irradiance", 1)):
        for s, e in _runs(d["flag"], flag, gap):
            n = (e - s).days + 1
            if n < MIN_DAYS[flag]:
                continue
            events.append(_build_event(d, s, e, flag, site_id, last_day, price_usd_kwh))
    events = _merge_fragments(sorted(events, key=lambda ev: ev.start), d, site_id, last_day, price_usd_kwh)
    d["event_kind"] = None
    for ev in events:
        d.loc[ev.start:ev.end, "event_kind"] = ev.kind
    return sorted(events, key=lambda ev: ev.start), d


def _merge_fragments(events: list[Event], d, site_id, last_day, price, max_gap_days: int = 7) -> list[Event]:
    """Join fragments of one problem that dip in and out of the threshold.

    - partial outages under a week apart: one unfixed fault with good days in between
    - a slow slide (soiling) that crosses the line, dips back and crosses again, up to two
      weeks apart, including a small-step fragment just before it
    """
    out: list[Event] = []
    for ev in events:
        prev = out[-1] if out else None
        gap = (pd.Timestamp(ev.start) - pd.Timestamp(prev.end)).days if prev else None
        same_outage = (prev and ev.kind == prev.kind == "partial_outage" and gap <= max_gap_days)
        slide = (prev and ev.kind == "soiling" and prev.kind in ("soiling", "partial_outage")
                 and (prev.evidence.get("step_drop") or 0) <= 0.08 and gap <= 2 * max_gap_days)
        if same_outage or slide:
            out[-1] = _build_event(d, pd.Timestamp(prev.start), pd.Timestamp(ev.end), "low",
                                   site_id, last_day, price, force_kind=ev.kind)
        else:
            out.append(ev)
    return out


def _build_event(d, s, e, flag, site_id, last_day, price, force_kind: str | None = None) -> Event:
    win = d.loc[s:e]
    before = d.loc[s - pd.Timedelta(days=14): s - pd.Timedelta(days=1)]
    before = before[before["flag"] == "ok"]
    pi_before = _r(before["pi"].median())
    pi_during = _r(win["pi"].median())
    base = win["baseline_pi"]
    lost = (win["expected_kwh_day"] * base - win["actual_kwh_day"]).clip(lower=0)
    expected_total = float((win["expected_kwh_day"] * base).sum())
    evidence = {
        "baseline_pi": _r(base.median()),
        "daily_pi": {k.strftime("%Y-%m-%d"): _r(v) for k, v in win["pi"].items() if pd.notna(v)},
    }

    if flag == "outage":
        kind = "outage"
    elif flag == "high":
        kind = "sensor_fault"
        evidence["reason"] = ("Output is above what the measured irradiance allows, so the "
                              "irradiance sensor is most likely reading low (dirty, drifting or misaligned).")
    elif flag == "capped":
        kind = "curtailment"
        evidence["plateau_frac"] = _r(win.loc[win["flag"] == "capped", "plateau_frac"].median())
        evidence["capped_days"] = int((win["flag"] == "capped").sum())
        evidence["reason"] = ("Output matches expectation in the morning and evening but is capped at midday on "
                              "sunny days, which points to an export limit or inverter power setpoint rather "
                              "than lost capacity.")
    elif flag == "stalled":
        kind = "tracker_stall"
        evidence["shape_gap"] = _r(win.loc[win["flag"] == "stalled", "shape_gap"].median())
        evidence["stalled_days"] = int((win["flag"] == "stalled").sum())
        evidence["reason"] = ("Output holds up at midday but falls short in the morning and evening, the "
                              "signature of tracker rows that stopped following the sun (parked or stuck).")
    elif flag == "no_irradiance":
        kind = "sensor_fault"
        evidence["reason"] = "The site produced power but the irradiance sensor reported nothing."
        evidence["poa_coverage"] = _r(win["poa_coverage"].mean())
    elif flag == "data_gap":
        kind = "data_gap"
        evidence["reason"] = "No meter readings during daylight; output during this window is unknown."
    else:
        kind, feats = _classify_low(d, s, e)
        if force_kind and force_kind != kind:
            kind = force_kind
            feats["reason"] = {
                "soiling": ("A slow slide that crossed the alert threshold more than once, the signature of "
                            "dust or pollen build-up (or gradual degradation)."),
                "partial_outage": ("Repeated drops below the threshold with only a few normal days between them, "
                                   "most likely one fault that comes and goes (an intermittent inverter or string "
                                   "trip) rather than separate problems."),
            }.get(kind, feats.get("reason", ""))
        evidence.update(feats)

    if kind in ("outage", "partial_outage"):
        snowy, feats = _looks_like_snow(d, s, e)
        if snowy:
            kind = "snow"
            evidence.update(feats)
            evidence["reason"] = ("Output collapsed but didn't switch off, right after freezing weather, while the "
                                  "irradiance sensor still saw sun: the panels are most likely covered by snow. "
                                  "Usually clears on its own as it melts.")

    if kind in ("data_gap", "sensor_fault"):
        lost_kwh, loss_pct = 0.0, None  # unknown / no production lost
    else:
        if flag in ("capped", "stalled"):
            lost = lost[win["flag"] == flag]  # the in-between (cloudy) days weren't affected
        lost_kwh = float(lost.sum())
        loss_pct = _r(100 * lost_kwh / expected_total) if expected_total > 0 else None

    active = e >= last_day - pd.Timedelta(days=1)
    return Event(
        site_id=site_id, kind=kind, start=s.strftime("%Y-%m-%d"), end=e.strftime("%Y-%m-%d"),
        days=(e - s).days + 1, active=bool(active),
        severity=_severity(kind, loss_pct, (e - s).days + 1, active),
        pi_before=pi_before, pi_during=pi_during, energy_lost_kwh=round(lost_kwh, 1),
        est_cost_usd=round(lost_kwh * price, 2), loss_pct=loss_pct, evidence=evidence,
    )


def _classify_low(d: pd.DataFrame, s, e) -> tuple[str, dict]:
    win = d.loc[s:e]
    judged = win[win["judged"]]
    dev = judged["dev"].dropna()
    x = np.asarray((dev.index - s).days, dtype=float)
    slope = float(np.polyfit(x, dev.to_numpy(), 1)[0]) if len(dev) >= 4 else 0.0
    before = d.loc[s - pd.Timedelta(days=10): s - pd.Timedelta(days=1)]
    before_dev = before.loc[before["judged"], "dev"].median()
    first_dev = dev.iloc[:3].median() if len(dev) else np.nan
    step = float(before_dev - first_dev) if pd.notna(before_dev) and pd.notna(first_dev) else np.nan
    shape_gap = float(judged["shape_gap"].median()) if judged["shape_gap"].notna().any() else 0.0
    # Trend over the month leading in plus the event: a short run at the start of a slow
    # slide looks flat on its own, but not in context
    ctx = d.loc[s - pd.Timedelta(days=30): e]
    ctx = ctx.loc[ctx["judged"], "dev"].dropna()
    cx = np.asarray((ctx.index - s).days, dtype=float)
    ctx_slope = float(np.polyfit(cx, ctx.to_numpy(), 1)[0]) if len(ctx) >= 10 else 0.0
    # How long the decline was underway before it crossed the threshold
    decline_lead = None
    clear = judged[judged["variability"] < CLEAR_DAY_VARIABILITY]
    plateau = float(clear["plateau_frac"].median()) if clear["plateau_frac"].notna().any() else 0.0
    clear_gap = float(clear["shape_gap"].median()) if clear["shape_gap"].notna().any() else 0.0
    feats = {"step_drop": _r(step), "trend_per_day": round(slope, 4),
             "trend_30d_per_day": round(ctx_slope, 4), "plateau_frac": _r(plateau)}

    if plateau > PLATEAU_FRAC and clear_gap > CAPPED_SHAPE_GAP:
        kind = "curtailment"
        feats["reason"] = ("Output matches expectation in the morning and evening but is capped at midday, "
                           "which points to an export limit, inverter setting, or clipping rather than lost capacity.")
    elif (slope < -0.0015 or ctx_slope < -0.0015) and not (step > 0.08):
        kind = "soiling"
        lead = d.loc[:s, "dev"].iloc[-60:]
        crossed = lead[lead > 0.99]
        if len(crossed):
            decline_lead = (s - crossed.index[-1]).days
            feats["decline_began"] = crossed.index[-1].strftime("%Y-%m-%d")
        after = d.loc[e + pd.Timedelta(days=1): e + pd.Timedelta(days=7)]
        rec = after.loc[after["judged"], "dev"].median()
        feats["recovered_to"] = _r(rec)
        feats["reason"] = ("A slow, steady slide in performance with no sudden step, the signature of "
                           "dust or pollen build-up (or gradual degradation)"
                           + (", followed by a sharp recovery consistent with rain or cleaning." if pd.notna(rec) and rec > 0.97 else "."))
    else:
        kind = "partial_outage"
        feats["reason"] = ("Performance stepped down abruptly and stayed flat, the signature of a share of the "
                           "array going offline (an inverter, a combiner or a string).")
        if pd.notna(first_dev):
            feats["capacity_offline_pct"] = _r(100 * (1 - first_dev))
    if decline_lead is not None:
        feats["decline_lead_days"] = decline_lead
    return kind, feats


def _severity(kind: str, loss_pct: float | None, days: int, active: bool) -> str:
    if kind == "outage":
        return "critical" if active else "high"
    if kind == "partial_outage":
        return "high" if (loss_pct or 0) >= 15 or active else "medium"
    if kind == "soiling":
        return "medium" if (loss_pct or 0) >= 6 else "low"
    if kind == "sensor_fault":
        return "medium"
    if kind == "tracker_stall":
        return "high" if active else "medium"
    if kind == "snow":
        return "medium" if days > 5 else "low"
    if kind == "data_gap":
        return "medium" if days >= 3 or active else "low"
    return "low"  # curtailment: usually external, confirm with the utility


def _r(x, n: int = 3):
    return None if x is None or pd.isna(x) else round(float(x), n)


# --------------------------------------------------------------------------- backtest

def backtest(events: list[Event], truth: pd.DataFrame) -> pd.DataFrame:
    """Match detected events to injected ones (any day overlap).

    Returns one row per true fault: whether it was found, the label given, and how many
    days after the fault started the event was flagged.
    """
    rows = []
    for t in truth.itertuples():
        ts, te = pd.Timestamp(t.start), pd.Timestamp(t.end)
        hits = [ev for ev in events if pd.Timestamp(ev.start) <= te and pd.Timestamp(ev.end) >= ts]
        best = min(hits, key=lambda ev: abs((pd.Timestamp(ev.start) - ts).days)) if hits else None
        rows.append({
            "true_kind": t.kind, "start": t.start, "end": t.end,
            "detected": best is not None,
            "detected_kind": best.kind if best else None,
            "correct_kind": bool(best and best.kind == t.kind),
            "delay_days": (pd.Timestamp(best.start) - ts).days if best else None,
        })
    return pd.DataFrame(rows)


def false_alarms(events: list[Event], truth: pd.DataFrame) -> list[Event]:
    """Detected events that overlap no injected fault."""
    spans = [(pd.Timestamp(t.start), pd.Timestamp(t.end)) for t in truth.itertuples()]
    return [ev for ev in events if not any(
        pd.Timestamp(ev.start) <= te and pd.Timestamp(ev.end) >= ts for ts, te in spans)]
