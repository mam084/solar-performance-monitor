"""Solar Performance Monitor: fleet overview, site drill-down, and the ticket approval queue.

Run locally:   streamlit run streamlit_app.py
Reads the pipeline's outputs in data/processed/<id>/ (see `python -m solarmon.pipeline`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from solarmon import review  # noqa: E402
from solarmon.config import DATA_DIR, load_sites  # noqa: E402
from solarmon.detect import KIND_LABELS  # noqa: E402
from solarmon.tickets import draft_ticket  # noqa: E402

st.set_page_config(page_title="Solar Performance Monitor", page_icon="☀️", layout="wide")

# Chart palette (validated reference palette): two series + status colors + chrome
ACTUAL, EXPECTED = "#2a78d6", "#eb6834"
INK, INK_2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SEVERITY_COLOR = {"critical": "#d03b3b", "high": "#ec835a", "medium": "#fab219", "low": "#898781"}
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
STATUS_ICON = {"pending_review": "⏳", "approved": "✅", "rejected": "✖️"}
PROCESSED = DATA_DIR / "processed"


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
    mtime = (site_dir(system_id) / "meta.json").stat().st_mtime
    return load_site_outputs(system_id, mtime)


def api_key() -> str | None:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:  # noqa: BLE001 - no secrets file
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


# --------------------------------------------------------------------------- charts

def _style(fig: go.Figure, height: int = 340, y_title: str = "") -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor="#fcfcfb",
        paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK_2, size=12),
        hovermode="x unified", legend=dict(orientation="h", y=1.08, x=0, font=dict(color=INK_2)),
        hoverlabel=dict(bgcolor="white", font_color=INK),
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, ticks="outside", tickcolor=AXIS)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=AXIS, title=y_title)
    return fig


def pi_chart(daily: pd.DataFrame, events: list[dict], window: tuple | None = None,
             height: int = 340, legend: bool = True) -> go.Figure:
    """Daily PI with events shaded by severity; full-history view numbers them to match the table."""
    d = daily if window is None else daily.loc[window[0]:window[1]]
    fig = go.Figure()
    for i, ev in enumerate(events, 1):
        s, e = pd.Timestamp(ev["start"]), pd.Timestamp(ev["end"]) + pd.Timedelta(days=1)
        if s > d.index.max() or e < d.index.min():
            continue
        fig.add_vrect(x0=s, x1=e, fillcolor=SEVERITY_COLOR[ev["severity"]], opacity=0.18,
                      line_width=0, layer="below")
        fig.add_annotation(x=s + (e - s) / 2, y=1.0, yref="paper", showarrow=False,
                           text=str(i) if window is None else ev["label"],
                           hovertext=f"{ev['label']}, {ev['start']} to {ev['end']}",
                           font=dict(size=11, color=INK_2), yanchor="bottom")
    fig.add_trace(go.Scatter(x=d.index, y=d["baseline_pi"], name="Baseline", mode="lines",
                             line=dict(color=MUTED, width=1.5, dash="dot"),
                             hovertemplate="%{y:.2f}"))
    fig.add_trace(go.Scatter(x=d.index, y=d["pi"], name="Daily PI", mode="markers",
                             marker=dict(color=ACTUAL, size=8, opacity=0.55, line=dict(width=0)),
                             hovertemplate="%{y:.2f}"))
    fig.add_trace(go.Scatter(x=d.index, y=d["pi"].rolling(30, min_periods=10, center=True).median(),
                             name="30-day median", mode="lines", line=dict(color=ACTUAL, width=2),
                             hovertemplate="%{y:.2f}"))
    _style(fig, height, "Performance index")
    fig.update_yaxes(range=[0, 1.35])
    fig.update_layout(margin=dict(t=40), showlegend=legend)
    return fig


def intraday_chart(intraday: pd.DataFrame, start, end, height: int = 320) -> go.Figure:
    w = intraday.loc[start:end]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=w.index, y=w["expected_ac_kw"], name="Expected", mode="lines",
                             line=dict(color=EXPECTED, width=2), hovertemplate="%{y:,.0f} kW"))
    fig.add_trace(go.Scatter(x=w.index, y=w["ac_power_kw"], name="Actual", mode="lines",
                             line=dict(color=ACTUAL, width=2), hovertemplate="%{y:,.0f} kW"))
    return _style(fig, height, "AC power (kW)")


# --------------------------------------------------------------------------- sidebar

sites = load_sites()
have = available_sites()

with st.sidebar:
    st.markdown("### ☀️ Solar Performance Monitor")
    st.caption("Actual vs weather-expected output, automatic fault detection, "
               "and agent-drafted maintenance tickets with human approval.")
    if not have:
        st.error("No processed data yet. Run `python -m solarmon.pipeline build 2107 --demo`.")
        st.stop()
    site_id = st.selectbox("Site", have, index=have.index(2107) if 2107 in have else 0, format_func=lambda i: f"{i} · {sites[i].name}" if i in sites else str(i))
    reviewer = st.text_input("Your name (for the approval log)", value=st.session_state.get("reviewer", ""))
    st.session_state["reviewer"] = reviewer
    st.divider()
    st.caption("Data: NREL PVDAQ (CC BY 4.0) · "
               "[Source code](https://github.com/mam084/solar-performance-monitor)")

meta, events, daily, intraday = outputs(site_id)
sdir = site_dir(site_id)
site = meta["site"]

n_demo = sum(outputs(i)[0]["source"] == "demo" for i in have)
if meta["source"] == "demo":
    who = "every site" if n_demo == len(have) else "this site"
    st.info(f"**Demo data** for {who}. The weather is physics-based (each site's real sun position, "
            "mounting and climate) and the faults are injected, so the detector can be checked against "
            "the truth. Real PVDAQ data swaps in with one command; see the Method tab.", icon="🧪")

tab_fleet, tab_site, tab_queue, tab_method = st.tabs(
    ["Fleet overview", "Site detail", "Ticket queue", "Method"])

# --------------------------------------------------------------------------- fleet

with tab_fleet:
    all_tickets, rows, n_active, lost_90, cost_90 = [], [], 0, 0.0, 0.0
    for sid in have:
        m, evs, dly, _ = outputs(sid)
        tk = review.load_tickets(site_dir(sid))
        all_tickets += tk
        last = dly["pi"].dropna()
        recent = last.loc[last.index.max() - pd.Timedelta(days=29):]
        active = [e for e in evs if e["active"]]
        n_active += len(active)
        cutoff = last.index.max() - pd.Timedelta(days=90)
        recent_evs = [e for e in evs if pd.Timestamp(e["end"]) >= cutoff]
        lost_90 += sum(e["energy_lost_kwh"] for e in recent_evs)
        cost_90 += sum(e["est_cost_usd"] for e in recent_evs)
        rows.append({
            "Site": f"{sid} · {m['site']['name']}", "Location": m["site"]["location"],
            "Size (kW DC)": m["site"]["dc_capacity_kw"], "Data through": m["data_end"],
            "PI, last 30 days": round(recent.median(), 3) if len(recent) else None,
            "Active issues": ", ".join(e["label"] for e in active) or "None",
            "Awaiting review": sum(t["status"] == "pending_review" for t in tk),
        })
    for sid, s in sites.items():
        if sid not in have:
            rows.append({"Site": f"{sid} · {s.name}", "Location": s.location,
                         "Size (kW DC)": s.dc_capacity_kw, "Data through": "",
                         "PI, last 30 days": None, "Active issues": "Not yet onboarded",
                         "Awaiting review": None})

    c = st.columns(4)
    c[0].metric("Sites monitored", f"{len(have)} of {len(sites)}")
    c[1].metric("Active issues", n_active)
    c[2].metric("Tickets awaiting review", sum(t["status"] == "pending_review" for t in all_tickets))
    c[3].metric("Energy lost, last 90 days", f"{lost_90:,.0f} kWh",
                help=f"About ${cost_90:,.0f} at ${meta['price_usd_kwh']}/kWh")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"PI, last 30 days": st.column_config.NumberColumn(format="%.2f")})
    st.caption("PI (performance index) = actual energy ÷ the energy the site's own irradiance and "
               "temperature sensors say it should have produced. A healthy site sits near 1.0 in any weather.")

# --------------------------------------------------------------------------- site

with tab_site:
    st.subheader(f"{site['name']} · {site['location']}")
    st.caption(f"{site['dc_capacity_kw']:,.0f} kW DC · {site['mount'].replace('_', '-')} mount, "
               f"{site['tilt']}° tilt · data {meta['data_start']} to {meta['data_end']}")
    c = st.columns(4)
    c[0].metric("Model error, healthy days", f"{meta['nrmse_healthy_pct']:.1f}%",
                help="nRMSE of 15-min expected vs actual power on days with no detected event. Target < 5%.")
    c[1].metric("Calibration scale", f"{meta['calibration_scale']:.3f}",
                help="Fit on the reference window: real-world losses vs the nameplate PVWatts model.")
    c[2].metric("Inverter AC limit", f"{meta['ac_capacity_kw']:,.0f} kW")
    c[3].metric("Events detected", len(events))

    st.markdown("**Daily performance index** · shaded spans are detected events, numbered as in the table below")
    st.plotly_chart(pi_chart(daily, events), width="stretch")

    if events:
        ev_df = pd.DataFrame([{
            "#": i,
            "Severity": f"{SEVERITY_ICON[e['severity']]} {e['severity']}", "Event": e["label"],
            "Start": e["start"], "End": "ongoing" if e["active"] else e["end"], "Days": e["days"],
            "PI during": e["pi_during"], "Energy lost (kWh)": e["energy_lost_kwh"] or None,
            "Est. cost ($)": e["est_cost_usd"] or None,
        } for i, e in enumerate(events, 1)])
        st.dataframe(ev_df, hide_index=True, width="stretch",
                     column_config={"Energy lost (kWh)": st.column_config.NumberColumn(format="%,.0f"),
                                    "Est. cost ($)": st.column_config.NumberColumn(format="$%,.0f"),
                                    "PI during": st.column_config.NumberColumn(format="%.2f")})

        pick = st.selectbox("Inspect an event", range(len(events)),
                            format_func=lambda i: f"{events[i]['start']} · {events[i]['label']}")
        ev = events[pick]
        s = pd.Timestamp(ev["start"]) - pd.Timedelta(days=2)
        e = min(pd.Timestamp(ev["start"]) + pd.Timedelta(days=5), pd.Timestamp(ev["end"]) + pd.Timedelta(days=2))
        e = e + pd.Timedelta(hours=23, minutes=45)
        st.markdown(f"**Actual vs expected power, {s:%b %d} to {e:%b %d}** · "
                    "the gap between the lines is the problem")
        st.plotly_chart(intraday_chart(intraday, s, e), width="stretch")
        st.caption(ev["evidence"].get("reason", ""))

    if meta.get("backtest"):
        with st.expander("Detector backtest against the injected faults"):
            b = meta["backtest"]
            st.write(f"Found **{b['detected']} of {b['faults_injected']}** injected faults, labelled "
                     f"**{b['correct_kind']}** correctly, with **{b['false_alarms']}** false alarms.")
            st.dataframe(pd.DataFrame(b["rows"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- queue

with tab_queue:
    tickets = review.load_tickets(sdir)
    ev_by_id = {e["id"]: e for e in events}
    key = api_key()

    top = st.columns([3, 2, 2])
    show = top[0].segmented_control(
        "Show", ["pending_review", "approved", "rejected", "all"], default="pending_review",
        format_func=lambda s: {"pending_review": "Awaiting review", "approved": "Approved",
                               "rejected": "Rejected", "all": "All"}[s])
    approved = [t for t in tickets if t["status"] == "approved"]
    top[1].download_button("Export approved (JSON)", json.dumps(approved, indent=2),
                           file_name=f"approved_tickets_{site_id}.json", disabled=not approved,
                           width="stretch")
    if top[2].button("Reset all decisions", width="stretch",
                     help="Clears approvals and rejections for this site. Drafts stay."):
        review.reset(sdir)
        st.rerun()

    if not key:
        st.caption("Drafts are from the built-in template. Add `ANTHROPIC_API_KEY` to the app's "
                   "secrets to redraft any ticket with Claude.")

    order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    shown = [t for t in tickets if show in (None, "all") or t["status"] == show]
    shown.sort(key=lambda t: (not ev_by_id.get(t["event_id"], {}).get("active", False),
                              order.get(t["priority"], 9), t["event_id"]))
    if not shown:
        st.success("Nothing here. The queue is clear.")

    for n, t in enumerate(shown):
        ev = ev_by_id.get(t["event_id"], {})
        sev = ev.get("severity", "low")
        live = " · **ONGOING**" if ev.get("active") else ""
        head = f"{STATUS_ICON[t['status']]} {SEVERITY_ICON[sev]} **{t['priority']}**{live} · {t['title']}"
        with st.expander(head, expanded=(n == 0 and t["status"] == "pending_review")):
            left, right = st.columns([3, 2])
            with right:
                if ev:
                    w0 = pd.Timestamp(ev["start"]) - pd.Timedelta(days=30)
                    w1 = pd.Timestamp(ev["end"]) + pd.Timedelta(days=14)
                    st.plotly_chart(pi_chart(daily, [ev], (w0, w1), height=220, legend=False), width="stretch",
                                    key=f"pi_{t['ticket_id']}")
                st.caption("Daily PI (dots), 30-day median (line), baseline (dotted)")
                st.markdown("**Evidence**")
                for line in t.get("evidence", []):
                    st.markdown(f"- {line}")
                if t.get("likely_causes"):
                    st.markdown("**Likely causes**")
                    for line in t["likely_causes"]:
                        st.markdown(f"- {line}")
                st.caption(f"Drafted by {t['drafted_by']} at {t['drafted_at']}"
                           + (f" · {t['draft_note']}" if t.get("draft_note") else ""))
            with left:
                tid = t["ticket_id"]
                locked = t["status"] != "pending_review"
                title = st.text_input("Title", t["title"], key=f"title_{tid}", disabled=locked)
                prio = st.selectbox("Priority", ["P1", "P2", "P3", "P4"],
                                    index=["P1", "P2", "P3", "P4"].index(t["priority"]),
                                    key=f"prio_{tid}", disabled=locked)
                summary = st.text_area("Summary", t["summary"], key=f"sum_{tid}", disabled=locked)
                actions = st.text_area("Recommended actions (one per line)",
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
                    st.markdown(f"**{t['status'].replace('_', ' ').title()}** by {t.get('reviewer')} "
                                f"at {t.get('reviewed_at')}"
                                + (f": _{t['review_note']}_" if t.get("review_note") else ""))
                    if st.button("Reopen for review", key=f"reopen_{tid}"):
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
                                   width="stretch"):
                        with st.spinner("Claude is drafting from the evidence..."):
                            new = draft_ticket(ev, site, use_claude=True, api_key=key)
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

# --------------------------------------------------------------------------- method

with tab_method:
    st.markdown(f"""
### How it works

1. **Expected output.** NREL's PVWatts model turns the site's own plane-of-array irradiance and
   temperature into the power it *should* produce. One scale factor, fit on a known-good reference
   window ({meta['reference_window'][0][:10]} to {meta['reference_window'][1][:10]} here), absorbs the
   site's real-world losses; the inverter's AC limit is kept so clipping isn't flagged as a fault.
2. **Performance index.** Daily actual ÷ expected energy over productive hours. Cloudy days
   don't move it, because the model sees the same clouds.
3. **Detection.** Each day is compared with a rolling baseline (75th percentile of recent PI,
   recomputed without flagged days so a long fault doesn't become the new normal). Runs of
   flagged days become events, classified by shape:

| Event | Signature |
|---|---|
| Full outage | PI near zero |
| Partial outage | Abrupt step down, then flat (an inverter, string or fuse) |
| Soiling / gradual loss | Slow slide, often reset by rain or a wash |
| Curtailment | Normal mornings and evenings, capped at midday |
| Irradiance sensor fault | Output *above* what the sensor allows, or no sensor data |
| Monitoring data gap | No meter readings in daylight |

4. **Ticket agent.** Each event gets a draft ticket built from a fixed evidence packet:
   numbers, dates, shape features and an O&M playbook. With an API key, Claude writes the
   draft through a forced tool call, so the output always matches the ticket schema and it
   can't invent readings that aren't in the packet. Nothing is dispatched until a person
   approves it here, and every decision is logged with who made it and what they changed.

### Data
NREL [PVDAQ](https://data.openei.org/submissions/4568) public PV data (CC BY 4.0).
To swap the demo for real data:

```bash
python -m solarmon.ingest download 2107 --include meter irradiance environment
python -m solarmon.pipeline build 2107
```
""")
