"""Underperformance detection and event classification.

Works on the daily performance index (PI = actual / expected energy) plus the 15-min
frame it came from. Three steps:

1. **Baseline.** Each day is compared with what's normal *for this site lately*: a
   rolling 75th percentile of recent PI, recomputed with flagged days left out so a
   long fault doesn't become the new normal. Its ratio to the baseline is `dev`.
2. **Daily flags.** outage (dev < 0.15), low (dev < 0.93), high (dev > 1.10, output
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
    })
    cal = pd.date_range(day.min(), day.max(), freq="D")
    d = daily.reindex(cal).join(full.reindex(cal))
    d["poa_coverage"] = d["poa_coverage"].fillna(1.0)
    return d


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


def add_baseline(d: pd.DataFrame, window_days: int = 90) -> pd.DataFrame:
    """Rolling baseline PI and each day's deviation from it, robust to long faults."""
    d = d.copy()
    pi = d["pi"]
    judged = d["poa_kwh_m2"].fillna(0) >= DARK_DAY_KWH_M2
    usable = pi.where(judged & pi.between(0.3, 1.5))
    mask = pd.Series(True, index=d.index)
    for _ in range(2):  # second pass ignores days the first pass flagged
        src = usable.where(mask)
        base = src.rolling(f"{window_days}D", min_periods=15).quantile(0.75).shift(1)
        # Before there's enough history, use the early-period level
        early = src.dropna().iloc[:60].quantile(0.75) if src.notna().any() else 1.0
        base = base.fillna(early).clip(0.7, 1.2)
        dev = pi / base
        mask = ~((dev < LOW_DEV) | (dev > HIGH_DEV))
    d["baseline_pi"] = base
    d["dev"] = dev
    d["judged"] = judged
    return d


def flag_days(d: pd.DataFrame) -> pd.Series:
    """One flag per day: outage, low, high, data_gap, no_irradiance, dark, ok, or none."""
    f = pd.Series("ok", index=d.index, dtype=object)
    f[d["pi"].isna() & d["producing_intervals"].fillna(0).eq(0)] = "none"  # night-only / no data
    f[~d["judged"]] = "dark"
    f[d["dev"] < LOW_DEV] = "low"
    f[d["dev"] > HIGH_DEV] = "high"
    # Output capped at midday (fine morning and evening): only shows on sunny days
    f[(d["dev"] < CAPPED_DEV) & (d["shape_gap"] > CAPPED_SHAPE_GAP) & d["judged"]] = "capped"
    # The reverse shape: short in the morning and evening, fine at midday (trackers parked flat)
    f[(d["dev"] < CAPPED_DEV) & (d["shape_gap"] < -CAPPED_SHAPE_GAP) & d["judged"]] = "stalled"
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
                  price_usd_kwh: float = DEFAULT_PRICE_USD_KWH) -> tuple[list[Event], pd.DataFrame]:
    """Find and classify events. Returns (events, the daily table with baseline and flags)."""
    d = add_baseline(daily_frame(out, daily))
    d["flag"] = flag_days(d)
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


def _merge_fragments(events: list[Event], d, site_id, last_day, price, max_gap_days: int = 14) -> list[Event]:
    """A slow slide can cross the threshold, dip back, and cross again. Join soiling
    events (and a low-run fragment just before one) that are under two weeks apart."""
    out: list[Event] = []
    for ev in events:
        prev = out[-1] if out else None
        if (prev and ev.kind == "soiling" and prev.kind in ("soiling", "partial_outage")
                and (prev.evidence.get("step_drop") or 0) <= 0.08
                and (pd.Timestamp(ev.start) - pd.Timestamp(prev.end)).days <= max_gap_days):
            out[-1] = _build_event(d, pd.Timestamp(prev.start), pd.Timestamp(ev.end), "low",
                                   site_id, last_day, price, force_kind="soiling")
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
        evidence["shape_gap"] = _r(win.loc[win["flag"] == "capped", "shape_gap"].median())
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
            feats["reason"] = ("A slow slide that crossed the alert threshold more than once, the signature of "
                               "dust or pollen build-up (or gradual degradation).")
        evidence.update(feats)

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
    feats = {"step_drop": _r(step), "trend_per_day": round(slope, 4),
             "trend_30d_per_day": round(ctx_slope, 4), "shape_gap": _r(shape_gap)}

    if shape_gap > 0.12:
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
