"""Solar Performance Monitor: fleet overview, site drill-down, ticket review, and a glossary.

Run locally:   streamlit run streamlit_app.py
Reads the pipeline's outputs in data/processed/<id>/ (see `python -m solarmon.pipeline`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from solarmon import review  # noqa: E402
from solarmon.config import DATA_DIR, load_sites  # noqa: E402
from solarmon.glossary import GLOSSARY, define  # noqa: E402
from solarmon.tickets import draft_ticket, evidence_lines  # noqa: E402

st.set_page_config(page_title="Solar Performance Monitor", page_icon="☀️", layout="wide")

# Validated reference palette: two series, status colours, recessive chrome
ACTUAL, EXPECTED = "#2a78d6", "#eb6834"
INK, INK_2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SEVERITY_COLOR = {"critical": "#d03b3b", "high": "#ec835a", "medium": "#fab219", "low": "#898781"}
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
STATUS = {"pending_review": ("⏳", "Awaiting review"), "approved": ("✅", "Approved"),
          "rejected": ("✖️", "Rejected"), "historical": ("🗄️", "History")}
PROCESSED = DATA_DIR / "processed"
RANGES = {"Last 3 months": 92, "Last year": 366, "Everything": None}
TERMS = {k for g in GLOSSARY.values() for k in g}


# --------------------------------------------------------------------------- data

@st.cache_data
def load_site_outputs(system_id: int, mtime: float):
    d = PROCESSED / str(system_id)
    meta = json.loads((d / "meta.json").read_text())
    events = json.loads((d / "events.json").read_text())
    daily = pd.read_parquet(d / "daily.parquet")
    intraday = pd.read_parquet(d / "intraday.parquet")
    return meta, events, daily, intraday


def site_dir(system_id: int) -> Path:
    return PROCESSED / str(system_id)


def available_sites() -> list[int]:
    if not PROCESSED.exists():
        return []
    return sorted(int(p.name) for p in PROCESSED.iterdir() if (p / "meta.json").exists())


def outputs(system_id: int):
    return load_site_outputs(system_id, (site_dir(system_id) / "meta.json").stat().st_mtime)


def api_key() -> str | None:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:  # noqa: BLE001 - no secrets file
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


def nice_date(d) -> str:
    t = pd.Timestamp(d)
    return f"{t:%b} {t.day}, {t.year}"


def span(a, b) -> str:
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    if a == b:
        return nice_date(a)
    if a.year == b.year:
        return f"{a:%b} {a.day} – {b:%b} {b.day}, {b.year}"
    return f"{nice_date(a)} – {nice_date(b)}"


def money(x) -> str:
    return f"${x:,.0f}"


# --------------------------------------------------------------------------- charts

def _style(fig: go.Figure, height: int, y_title: str, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=12, b=8), plot_bgcolor="#fcfcfb",
        paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK_2, size=13),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0, font=dict(color=INK_2, size=13)),
        hoverlabel=dict(bgcolor="white", font_color=INK, font_size=13),
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, ticks="outside", tickcolor=AXIS, tickfont=dict(size=12))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=AXIS, tickfont=dict(size=12),
                     title=dict(text=y_title, font=dict(size=13)))
    return fig


def performance_chart(daily: pd.DataFrame, events: list[dict], start, end,
                      height: int = 380, compact: bool = False) -> go.Figure:
    """One dot per day (actual ÷ expected), its 30-day trend, the site's normal level,
    and detected problems as shaded bands with details on hover."""
    d = daily.loc[start:end]
    n_days = max((pd.Timestamp(end) - pd.Timestamp(start)).days, 1)
    fig = go.Figure()

    hover_x, hover_y, hover_text = [], [], []
    for ev in events:
        s, e = pd.Timestamp(ev["start"]), pd.Timestamp(ev["end"]) + pd.Timedelta(days=1)
        if s > pd.Timestamp(end) or e < pd.Timestamp(start):
            continue
        fig.add_vrect(x0=s, x1=e, fillcolor=SEVERITY_COLOR[ev["severity"]], opacity=0.22, line_width=0,
                      layer="below")
        lost = (f"<br>{ev['energy_lost_kwh']:,.0f} kWh lost (~{money(ev['est_cost_usd'])})"
                if ev["energy_lost_kwh"] else "")
        hover_x.append(s + (e - s) / 2)
        hover_y.append(1.36)
        hover_text.append(f"<b>{ev['label']}</b><br>{span(ev['start'], ev['end'])} · {ev['severity']} severity{lost}")

    fig.add_hline(y=1.0, line=dict(color=MUTED, width=1), layer="below")
    if not compact:
        fig.add_annotation(x=1, xref="paper", y=1.0, text="as expected", showarrow=False, xanchor="right",
                           yanchor="bottom", font=dict(size=11, color=MUTED))
    fig.add_trace(go.Scatter(
        x=d.index, y=d["pi"], name="Each day", mode="markers",
        marker=dict(color=ACTUAL, size=5 if n_days > 400 else 7, opacity=0.45, line=dict(width=0)),
        hovertemplate="%{x|%b %d, %Y}: <b>%{y:.0%}</b> of expected<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=d.index, y=d["pi"].rolling(30, min_periods=10, center=True).median(), name="30-day trend",
        mode="lines", line=dict(color=ACTUAL, width=2.5), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=d.index, y=d["baseline_pi"], name="Normal level for this site", mode="lines",
        line=dict(color=INK_2, width=1.5, dash="dot"), hoverinfo="skip"))
    if hover_x:
        fig.add_trace(go.Scatter(
            x=hover_x, y=hover_y, name="Detected problem (hover ▼)", mode="markers",
            marker=dict(symbol="triangle-down", size=11, color=INK_2), hovertext=hover_text,
            hovertemplate="%{hovertext}<extra></extra>"))
    _style(fig, height, "Actual ÷ expected output", legend=not compact)
    fig.update_yaxes(range=[0, 1.42], tickformat=".0%", dtick=0.2)
    fig.update_xaxes(range=[pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)])
    fig.update_layout(hovermode="closest")
    return fig


def power_chart(intraday: pd.DataFrame, start, end, ev: dict | None = None, height: int = 340) -> go.Figure:
    w = intraday.loc[start:end]
    fig = go.Figure()
    if ev is not None and len(w):
        s, e = pd.Timestamp(ev["start"]), pd.Timestamp(ev["end"]) + pd.Timedelta(days=1)
        fig.add_vrect(x0=max(s, w.index.min()), x1=min(e, w.index.max()),
                      fillcolor=SEVERITY_COLOR[ev["severity"]], opacity=0.15, line_width=0, layer="below")
    fig.add_trace(go.Scatter(x=w.index, y=w["expected_ac_kw"], name="Expected", mode="lines",
                             line=dict(color=EXPECTED, width=2), hovertemplate="Expected %{y:,.0f} kW<extra></extra>"))
    fig.add_trace(go.Scatter(x=w.index, y=w["ac_power_kw"], name="Actual", mode="lines",
                             line=dict(color=ACTUAL, width=2), hovertemplate="Actual %{y:,.0f} kW<extra></extra>"))
    _style(fig, height, "Power (kW)")
    fig.update_layout(legend=dict(y=-0.24))  # clear of the two-line day labels
    fig.update_xaxes(tickformat="%a<br>%b %d", dtick=24 * 3600 * 1000, hoverformat="%a %b %d, %H:%M")
    fig.update_layout(hovermode="x unified")
    return fig


# --------------------------------------------------------------------------- summaries

def plain_summary(meta: dict, events: list[dict]) -> str:
    """Two or three sentences a non-specialist can read first."""
    site = meta["site"]
    period = span(meta["data_start"], meta["data_end"])
    lost = [e for e in events if e["energy_lost_kwh"]]
    total_kwh = sum(e["energy_lost_kwh"] for e in lost)
    total_usd = sum(e["est_cost_usd"] for e in lost)
    parts = [f"Over the data period ({period}), the monitor found **{len(events)} problem{'s' * (len(events) != 1)}** at "
             f"{site['name']}"]
    if lost:
        parts[-1] += f", costing about **{total_kwh / 1000:,.0f} MWh ({money(total_usd)})** in total."
        big = max(lost, key=lambda e: e["est_cost_usd"])
        parts.append(f"The costliest was a {big['label'].lower()} ({span(big['start'], big['end'])}, "
                     f"{big['days']} days, about {money(big['est_cost_usd'])}).")
    else:
        parts[-1] += "."
    ongoing = [e for e in events if e["active"]]
    if ongoing:
        when = "when the data ends" if meta["source"] != "demo" else "at the end of the data"
        parts.append(f"Still going {when}: {', '.join(e['label'].lower() for e in ongoing)}.")
    h = meta.get("health") or {}
    if h.get("chronic_shortfall_pct", 0) >= 3.5:
        parts.append(f"On top of that, on ordinary days it runs about **{h['chronic_shortfall_pct']:.0f}% below "
                     f"its own best** (~{money(h['chronic_shortfall_usd_per_year'])} a year), which no single "
                     "day's alert would catch.")
    return " ".join(parts)


# --------------------------------------------------------------------------- page

sites = load_sites()
have = available_sites()

with st.sidebar:
    st.markdown("### ☀️ Solar Performance Monitor")
    st.caption("Compares what each solar site produced with what the weather says it should have, "
               "flags problems, and drafts maintenance tickets for a person to approve.")
    if not have:
        st.error("No processed data yet. Run `python -m solarmon.pipeline build 2107 --demo`.")
        st.stop()
    reviewer = st.text_input("Your name", value=st.session_state.get("reviewer", ""),
                             help="Saved with any ticket you approve or reject.")
    st.session_state["reviewer"] = reviewer
    st.divider()
    st.caption("New here? The **Help & glossary** tab explains every term, and most labels have a ⓘ "
               "you can hover.")
    st.caption("Data: NREL PVDAQ (CC BY 4.0) · "
               "[Source code](https://github.com/mam084/solar-performance-monitor)")

tab_fleet, tab_site, tab_tickets, tab_help = st.tabs(["Fleet", "Site", "Tickets", "Help & glossary"])

# --------------------------------------------------------------------------- fleet

with tab_fleet:
    st.subheader("All sites at a glance")
    all_tickets, rows, n_ongoing = [], [], 0
    for sid in have:
        m, evs, dly, _ = outputs(sid)
        tk = review.load_tickets(site_dir(sid))
        all_tickets += tk
        pi = dly["pi"].dropna()
        recent = pi.loc[pi.index.max() - pd.Timedelta(days=29):]
        ongoing = [e for e in evs if e["active"]]
        n_ongoing += len(ongoing)
        h = m.get("health") or {}
        short = h.get("chronic_shortfall_pct")
        rows.append({
            "Site": f"{m['site']['name']}, {m['site']['location']}",
            "Data": f"{'Demo' if m['source'] == 'demo' else 'Real'} {m['data_start'][:4]}–{m['data_end'][:4]}",
            "Size (kW)": m["site"]["dc_capacity_kw"],
            "Recent performance": f"{recent.median():.0%}" if len(recent) else "",
            "Everyday shortfall": f"{short:.0f}%" if short is not None else "",
            "Problems": len(evs),
            "Ongoing": ", ".join(e["label"] for e in ongoing) or "—",
            "Waiting": sum(t["status"] == "pending_review" for t in tk),
        })
    for sid, s in sites.items():
        if sid not in have:
            rows.append({"Site": f"{s.name}, {s.location}", "Data": "Not yet available",
                         "Size (kW)": s.dc_capacity_kw, "Recent performance": "", "Everyday shortfall": "",
                         "Problems": 0, "Ongoing": "—", "Waiting": 0})

    c = st.columns(4)
    n_real = sum(outputs(i)[0]["source"] != "demo" for i in have)
    c[0].metric("Sites", f"{len(have)}", help=f"{n_real} on real NREL data, {len(have) - n_real} on demo data. "
                + define("Demo data"))
    c[1].metric("Problems found", sum(r["Problems"] for r in rows), help=define("Problem (event)"))
    c[2].metric("Ongoing when data ends", n_ongoing, help=define("Ongoing"))
    c[3].metric("Tickets waiting for review", sum(t["status"] == "pending_review" for t in all_tickets),
                help=define("Awaiting review"))
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={
            "Size (kW)": st.column_config.NumberColumn(format="%.0f", help=define("Size (kW DC)")),
            "Data": st.column_config.TextColumn(help="Real NREL data or labelled demo data, and the years covered."),
            "Recent performance": st.column_config.TextColumn(
                help="Median over the last 30 days of the site's data. " + define("Performance (actual ÷ expected)")),
            "Everyday shortfall": st.column_config.TextColumn(help=define("Everyday shortfall")),
            "Problems": st.column_config.NumberColumn(help=define("Problem (event)")),
            "Ongoing": st.column_config.TextColumn(help=define("Ongoing")),
            "Waiting": st.column_config.NumberColumn(help=define("Awaiting review")),
        })
    st.caption("Each site's public data ends at a different date, so 'recent' means the last 30 days of that "
               "site's data. **100%** performance means a site produced exactly what its weather allowed. "
               "Open a site in the **Site** tab for the full picture.")

# --------------------------------------------------------------------------- site

with tab_site:
    names = {i: (outputs(i)[0]["site"]["name"] + f" ({i})") for i in have}
    site_id = st.selectbox("Site", have, index=have.index(2107) if 2107 in have else 0,
                           format_func=lambda i: names[i], key="site_pick")
    meta, events, daily, intraday = outputs(site_id)
    site = meta["site"]
    health = meta.get("health") or {}
    mount = "sun-tracking" if site["mount"] == "single_axis" else f"fixed, {site['tilt']}° tilt"
    st.subheader(f"{site['name']} · {site['location']}")
    st.caption(f"{site['dc_capacity_kw']:,.0f} kW of panels, {mount} · "
               f"{'demo data' if meta['source'] == 'demo' else 'real data from NREL'}, "
               f"{span(meta['data_start'], meta['data_end'])}")
    if meta["source"] == "demo":
        st.info("**Demo data.** " + define("Demo data"), icon="🧪")

    st.markdown(plain_summary(meta, events))

    lost_kwh = sum(e["energy_lost_kwh"] for e in events)
    lost_usd = sum(e["est_cost_usd"] for e in events)
    c = st.columns(4)
    acc = health.get("nrmse_full_health_pct")
    c[0].metric("Prediction accuracy", f"±{acc:.1f}%" if acc is not None else f"±{meta['nrmse_healthy_pct']:.1f}%",
                help=define("Prediction accuracy"))
    c[1].metric("Everyday shortfall",
                f"{health['chronic_shortfall_pct']:.1f}%" if "chronic_shortfall_pct" in health else "—",
                help=define("Everyday shortfall")
                + (f" Here: about {health['chronic_shortfall_mwh_per_year']:,.0f} MWh "
                   f"({money(health['chronic_shortfall_usd_per_year'])}) a year."
                   if "chronic_shortfall_pct" in health else ""))
    c[2].metric("Problems found", len(events), help=define("Problem (event)"))
    c[3].metric("Lost to problems", f"{lost_kwh / 1000:,.0f} MWh",
                help=define("Energy lost and cost") + f" Here: about {money(lost_usd)} in total.")

    warns = [ck for ck in meta.get("preflight", []) if ck["status"] != "PASS"]
    if acc is not None and acc < 5:  # preflight judges accuracy before the ML layer; the final number counts
        warns = [ck for ck in warns if ck["name"] != "accuracy"]
    if warns:
        with st.expander(f"⚠️ {len(warns)} data-quality note(s) for this site"):
            for ck in warns:
                st.markdown(f"- **{ck['name'].capitalize()}**: {ck['detail']}"
                            + (f"  \n  _Suggested fix:_ {ck['fix']}" if ck.get("fix") else ""))

    # ---- performance over time
    st.markdown("#### Performance over time")
    last = daily["pi"].dropna().index.max()
    first = daily.index.min()
    choice = st.segmented_control("Show", list(RANGES), default="Last year", key="range_pick")
    days = RANGES.get(choice or "Last year")
    start = first if days is None else max(first, last - pd.Timedelta(days=days))
    st.plotly_chart(performance_chart(daily, events, start, last), width="stretch")
    st.caption("Each dot is one day: what the site produced divided by what its sunlight and temperature say it "
               "should have. **100%** is right on target; 80% is 20% short. Clouds don't pull it down, because "
               "the expectation uses the same day's sunlight. Shaded bands are detected problems: hover the ▼ "
               "markers for details." + (f" The data ends {nice_date(last)}." if meta["source"] != "demo" else ""))

    # ---- problems table
    st.markdown("#### Problems found")
    if events:
        newest = sorted(events, key=lambda e: e["start"], reverse=True)
        table = pd.DataFrame([{
            "Problem": e["label"], "Severity": f"{SEVERITY_ICON[e['severity']]} {e['severity']}",
            "Dates": span(e["start"], e["end"]), "Days": e["days"],
            "Ongoing": "yes" if e["active"] else "",
            "Output vs expected": f"{e['pi_during']:.0%}" if e["pi_during"] is not None else "",
            "Energy lost": f"{e['energy_lost_kwh']:,.0f} kWh" if e["energy_lost_kwh"] else "",
            "Est. cost": money(e["est_cost_usd"]) if e["est_cost_usd"] else "",
        } for e in newest])
        st.dataframe(table, hide_index=True, width="stretch", height=min(36 * len(table) + 40, 380),
                     column_config={
                         "Problem": st.column_config.TextColumn(
                             help="Each type is explained in the Help & glossary tab."),
                         "Severity": st.column_config.TextColumn(help=define("Severity")),
                         "Ongoing": st.column_config.TextColumn(help=define("Ongoing")),
                         "Output vs expected": st.column_config.TextColumn(
                             help="What the site produced during the problem, as a share of expected."),
                         "Energy lost": st.column_config.TextColumn(help=define("Energy lost and cost")),
                         "Est. cost": st.column_config.TextColumn(help=define("Energy lost and cost")),
                     })
        st.caption("A blank loss means the true output is unknown (sensor faults and data gaps).")

        # ---- one problem up close
        st.markdown("#### Look at one problem up close")
        pick = st.selectbox("Problem", range(len(newest)), key=f"ev_pick_{site_id}",
                            format_func=lambda i: f"{newest[i]['label']} · {span(newest[i]['start'], newest[i]['end'])}"
                                                  + (" · ongoing" if newest[i]["active"] else ""))
        ev = newest[pick]
        s = pd.Timestamp(ev["start"]) - pd.Timedelta(days=2)
        e = min(pd.Timestamp(ev["start"]) + pd.Timedelta(days=5), pd.Timestamp(ev["end"]) + pd.Timedelta(days=2))
        e = e + pd.Timedelta(hours=23, minutes=45)
        left, right = st.columns([3, 2])
        with left:
            st.plotly_chart(power_chart(intraday, s, e, ev), width="stretch")
            st.caption("Orange is what the site should have produced, blue what it did. The shaded days are the "
                       "problem; the days either side show normal for comparison.")
            w = intraday.loc[s:e]
            producing = w["ac_power_kw"] > 1
            missing = w.loc[producing, "expected_ac_kw"].isna().mean() if producing.any() else 0
            if missing > 0.2:
                st.warning(f"No expected line for {missing:.0%} of this window: the sunlight sensor wasn't "
                           "reporting, and expected output is calculated from it.", icon="📡")
        with right:
            st.markdown(f"**{ev['label']}** · {SEVERITY_ICON[ev['severity']]} {ev['severity']} severity")
            if ev["label"] in TERMS:
                st.caption(define(ev["label"]))
            st.markdown("**What the data shows**")
            for line in evidence_lines(ev):
                st.markdown(f"- {line}")
    else:
        st.success("No problems detected at this site.")

    # ---- model accuracy, explained
    with st.expander("How accurate is the prediction, and what's behind it?"):
        ml = meta.get("ml") or {}
        ref = meta["reference_window"]
        txt = [
            "Expected output starts from NREL's **PVWatts** physics model, driven by this site's own sunlight and "
            f"temperature sensors and calibrated on a known-good year ({span(ref[0][:10], ref[1][:10])}). "
            "A correction learned from the site's history then fixes patterns that repeat every day, such as a "
            "sensor angled slightly differently from the panels."]
        if ml.get("adopted"):
            txt.append(f"A **machine-learning layer** is switched on here: it predicted the most recent quarter of "
                       f"the data (from {nice_date(ml['holdout_start'])}, which it never saw while learning) with "
                       f"±{ml['holdout_nrmse_ml']:.1f}% typical error, against ±{ml['holdout_nrmse_physics']:.1f}% "
                       "for physics alone.")
        elif "holdout_nrmse_physics" in ml:
            txt.append("A machine-learning layer was tested but **not** used here, because it didn't predict "
                       "recent data better than physics alone.")
        if acc is not None:
            txt.append(f"On clear days when the site was at its best, predictions are typically within "
                       f"**±{acc:.1f}%** of actual 15-minute output (target: under 5%). Counting every day without "
                       f"a detected problem it's ±{meta['nrmse_healthy_pct']:.1f}%: the difference is the plant's "
                       "own small, scattered losses, not the model.")
        st.markdown("\n\n".join(txt))

    if meta.get("backtest"):
        with st.expander("How well does the detector find planted faults?"):
            b = meta["backtest"]
            st.write(f"On this demo site it found **{b['detected']} of {b['faults_injected']}** planted faults, "
                     f"named **{b['correct_kind']}** correctly, with **{b['false_alarms']}** false alarms.")
            st.dataframe(pd.DataFrame(b["rows"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- tickets

with tab_tickets:
    st.subheader("Maintenance tickets")
    st.caption("Every detected problem gets a draft ticket. Review it, edit anything, then **approve** it to "
               "hand to the field team or **reject** it with a reason. Nothing is sent without a person's "
               "approval. Problems that ended long ago are filed under History.")
    key = api_key()
    site_names = {i: outputs(i)[0]["site"]["name"] for i in have}
    f = st.columns([2, 3])
    pick_site = f[0].selectbox("Site", ["all", *have], key="tk_site",
                               format_func=lambda i: "All sites" if i == "all" else f"{site_names[i]} ({i})")
    show = f[1].segmented_control("Show", ["pending_review", "approved", "rejected", "historical", "all"],
                                  default="pending_review", key="tk_status",
                                  format_func=lambda s: "All" if s == "all" else STATUS[s][1])
    scope = have if pick_site == "all" else [pick_site]

    tickets, ev_by_id, daily_by_site = [], {}, {}
    for sid in scope:
        m, evs, dly, _ = outputs(sid)
        daily_by_site[sid] = dly
        ev_by_id.update({e["id"]: e for e in evs})
        tickets += [{**t, "_site": sid} for t in review.load_tickets(site_dir(sid))]

    order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    shown = [t for t in tickets if show in (None, "all") or t["status"] == show]
    shown.sort(key=lambda t: (not ev_by_id.get(t["event_id"], {}).get("active", False),
                              order.get(t["priority"], 9), t["event_id"]))
    counts = {k: sum(t["status"] == k for t in tickets) for k in STATUS}
    st.caption(" · ".join(f"{STATUS[k][0]} {STATUS[k][1]}: {v}" for k, v in counts.items()))

    if not shown:
        st.success("Nothing here."
                   + (f" {counts['historical']} older problem(s) are under History."
                      if counts["historical"] and show == "pending_review" else ""))
    if not key and shown:
        st.caption("Drafts come from a built-in template. With an `ANTHROPIC_API_KEY` in the app's secrets, "
                   "each ticket can be redrafted by Claude.")

    for n, t in enumerate(shown[:60]):
        ev = ev_by_id.get(t["event_id"], {})
        sid = t["_site"]
        sdir = site_dir(sid)
        sev = ev.get("severity", "low")
        live = " · **ongoing**" if ev.get("active") else ""
        when = f" · {span(ev['start'], ev['end'])}" if ev else ""
        head = f"{STATUS[t['status']][0]} {SEVERITY_ICON[sev]} **{t['priority']}** · {site_names[sid]}{when}{live}"
        with st.expander(head, expanded=(n == 0 and t["status"] == "pending_review")):
            st.markdown(f"**{t['title']}**")
            left, right = st.columns([3, 2])
            with right:
                if ev:
                    w0 = pd.Timestamp(ev["start"]) - pd.Timedelta(days=30)
                    w1 = min(pd.Timestamp(ev["end"]) + pd.Timedelta(days=14), daily_by_site[sid].index.max())
                    st.plotly_chart(performance_chart(daily_by_site[sid], [ev], w0, w1, height=220, compact=True),
                                    width="stretch", key=f"pc_{t['ticket_id']}")
                    st.caption("Daily output as a share of expected; the shaded band is this problem.")
                st.markdown("**Evidence**")
                for line in t.get("evidence", []):
                    st.markdown(f"- {line}")
                if t.get("likely_causes"):
                    st.markdown("**Likely causes**")
                    for line in t["likely_causes"]:
                        st.markdown(f"- {line}")
                who = "Claude" if str(t["drafted_by"]).startswith("claude") else "the built-in template"
                st.caption(f"Drafted by {who}" + (f" · {t['draft_note']}" if t.get("draft_note") else ""))
            with left:
                tid = t["ticket_id"]
                locked = t["status"] != "pending_review"
                title = st.text_input("Title", t["title"], key=f"title_{tid}", disabled=locked)
                prio = st.selectbox("Priority", ["P1", "P2", "P3", "P4"],
                                    index=["P1", "P2", "P3", "P4"].index(t["priority"]),
                                    key=f"prio_{tid}", disabled=locked, help=define("Priority"))
                summary = st.text_area("Summary", t["summary"], key=f"sum_{tid}", disabled=locked)
                actions = st.text_area("Steps for the technician (one per line)",
                                       "\n".join(t["recommended_actions"]), height=150,
                                       key=f"act_{tid}", disabled=locked)
                parts = st.text_input("Parts and tools (comma separated)",
                                      ", ".join(t.get("parts_and_tools", [])), key=f"parts_{tid}",
                                      disabled=locked)
                edits = {"title": title, "priority": prio, "summary": summary,
                         "recommended_actions": [a.strip() for a in actions.splitlines() if a.strip()],
                         "parts_and_tools": [p.strip() for p in parts.split(",") if p.strip()]}
                changed = {k: v for k, v in edits.items() if v != t.get(k)}

                if locked:
                    if t["status"] == "historical":
                        st.markdown("**History.** " + define("History"))
                    else:
                        st.markdown(f"**{STATUS[t['status']][1]}** by {t.get('reviewer')} "
                                    f"on {str(t.get('reviewed_at', ''))[:10]}"
                                    + (f": _{t['review_note']}_" if t.get("review_note") else ""))
                    if st.button("Open for review" if t["status"] == "historical" else "Reopen for review",
                                 key=f"reopen_{tid}"):
                        review.record(sdir, tid, "pending_review", reviewer, "Reopened")
                        st.rerun()
                else:
                    note = st.text_input("Note (required to reject)", key=f"note_{tid}")
                    b = st.columns(3)
                    if b[0].button("Approve", type="primary", key=f"ok_{tid}", width="stretch"):
                        review.record(sdir, tid, "approved", reviewer, note, edits=changed)
                        st.toast(f"Approved: {title}")
                        st.rerun()
                    if b[1].button("Reject", key=f"no_{tid}", width="stretch"):
                        if not note.strip():
                            st.warning("Add a note saying why it's rejected.")
                        else:
                            review.record(sdir, tid, "rejected", reviewer, note, edits=changed)
                            st.rerun()
                    if b[2].button("Redraft with Claude", key=f"ai_{tid}", disabled=not key or not ev,
                                   width="stretch",
                                   help=None if key else "Needs an ANTHROPIC_API_KEY in the app's secrets."):
                        with st.spinner("Claude is drafting from the evidence..."):
                            new = draft_ticket(ev, outputs(sid)[0]["site"], use_claude=True, api_key=key)
                        fields = ("title", "priority", "summary", "evidence", "likely_causes",
                                  "recommended_actions", "parts_and_tools", "safety_notes",
                                  "drafted_by", "drafted_at", "draft_note")
                        review.record(sdir, tid, "pending_review", reviewer, "Redrafted",
                                      redraft={k: new.get(k) for k in fields if k in new})
                        for k in ("title", "prio", "sum", "act", "parts"):
                            st.session_state.pop(f"{k}_{tid}", None)
                        st.rerun()
                if t.get("safety_notes"):
                    st.caption(f"⚠️ {t['safety_notes']}")
    if len(shown) > 60:
        st.caption(f"Showing the first 60 of {len(shown)}. Pick one site to narrow the list.")

    st.divider()
    approved = [t for t in tickets if t["status"] == "approved"]
    b = st.columns([2, 2, 3])
    b[0].download_button("Download approved tickets", json.dumps(approved, indent=2, default=str),
                         file_name="approved_tickets.json", disabled=not approved, width="stretch",
                         help="A JSON file of approved tickets, ready to load into a work-order system.")
    if b[1].button("Clear review decisions", width="stretch",
                   help="Removes approvals and rejections for the site(s) shown. The drafts stay."):
        for sid in scope:
            review.reset(site_dir(sid))
        st.rerun()

# --------------------------------------------------------------------------- help

with tab_help:
    st.subheader("How it works")
    st.markdown("""
1. **Measure.** Each site reports its power output, and the sunlight and temperature at its panels, every 15 minutes.
2. **Predict.** A physics model turns that sunlight and temperature into the power the site *should* have made.
   It's calibrated to each site and learns the site's normal daily pattern.
3. **Compare.** Each day's actual energy is divided by the expected energy. 100% means on target whatever the
   weather, because the prediction uses the same day's sunlight.
4. **Detect.** Days that fall well below the site's normal level become *problems*, named by their pattern:
   a sudden step down, a slow slide, a midday cap, snow after a freeze, and so on.
5. **Draft and review.** Each problem gets a draft maintenance ticket with its evidence. A person approves,
   edits or rejects it; nothing is dispatched automatically.
6. **Stay current.** A scheduled job checks NREL for new data every morning and rebuilds what changed.
""")
    st.subheader("Glossary")
    cols = st.columns(2)
    for n, (group, terms) in enumerate(GLOSSARY.items()):
        with cols[n % 2]:
            st.markdown(f"##### {group}")
            st.markdown("\n".join(f"- **{term}.** {text}" for term, text in terms.items()))
    st.subheader("Data")
    st.markdown("Real data comes from NREL's public [PVDAQ](https://data.openei.org/submissions/4568) archive "
                "(CC BY 4.0). The technical write-up, including what the real data taught us, is in "
                "[docs/scaling.md](https://github.com/mam084/solar-performance-monitor/blob/main/docs/scaling.md).")
