"""Maintenance ticket drafting: turn a detected event into a ticket a human approves.

Two drafters share one output schema:

* `template_ticket` is deterministic and offline. Every event gets one, so the
  approval queue works with no API key.
* `claude_ticket` asks Claude to write the ticket from the same evidence packet,
  using a forced tool call so the reply is always valid, schema-shaped JSON.
  It falls back to the template on any error.

Nothing here acts on the site. A ticket only leaves `pending_review` when a person
approves or rejects it in the app.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

DEFAULT_MODEL = "claude-sonnet-5-5"
PRIORITY = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4"}

# What a seasoned O&M lead would tell a technician to do first, per event type.
PLAYBOOK = {
    "outage": {
        "actions": [
            "Check SCADA / inverter alarm log for the trip code and time of the first fault",
            "Confirm grid availability with the utility before dispatch (rule out a feeder outage)",
            "If alarms allow, attempt one remote reset; otherwise dispatch a technician",
            "On site: inspect inverter, AC disconnect and breakers; follow lockout/tagout",
        ],
        "parts": ["Inverter spare fuses", "Insulation-resistance tester (ground-fault trips)"],
    },
    "partial_outage": {
        "actions": [
            "Compare inverter- and combiner-level currents to locate the offline section",
            "Pull inverter fault logs for the start date",
            "Inspect combiner-box fuses and string connectors in the affected block",
            "Run IV-curve traces on suspect strings; replace failed fuses or components",
        ],
        "parts": ["Combiner fuses (matching rating)", "IV-curve tracer", "MC4 connectors"],
    },
    "soiling": {
        "actions": [
            "Visually inspect a sample of modules and photograph the soiling",
            "Compare against the decline start date and the last rain or wash",
            "Schedule a wash if the recoverable energy outweighs the cleaning cost; check the rain forecast first",
            "After cleaning, confirm the performance index returns to its baseline",
        ],
        "parts": ["Wash crew / water truck (deionised water)"],
    },
    "curtailment": {
        "actions": [
            "Ask the utility whether an export limit or curtailment order was in effect",
            "Check the plant controller and inverter active-power limit setpoints",
            "If no limit was ordered, restore the setpoint and document the change",
        ],
        "parts": [],
    },
    "sensor_fault": {
        "actions": [
            "Clean the plane-of-array pyranometer and check its level and tilt alignment",
            "Cross-check its readings against a second on-site sensor or satellite irradiance",
            "Recalibrate or replace the sensor if the offset persists",
            "Treat performance numbers for this window as unreliable until fixed",
        ],
        "parts": ["Spare pyranometer / reference cell", "Bubble level and inclinometer"],
    },
    "tracker_stall": {
        "actions": [
            "Check the tracker controller (TCU/NCU) for alarms, stow commands and lost communications",
            "Compare reported vs commanded row angles to find which rows are stuck",
            "Clear any wind or snow stow left active; reset the controller",
            "On site: inspect drive motors, slew gears and row power supplies on stuck rows",
        ],
        "parts": ["Spare tracker motor / controller board", "Inclinometer"],
    },
    "data_gap": {
        "actions": [
            "Check data-logger power and network/modem connectivity",
            "Back-fill the gap from inverter internal logs or the revenue meter",
            "Confirm the site was producing during the gap (meter totals)",
        ],
        "parts": ["Spare cellular modem / SIM"],
    },
}

TICKET_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "One line, under 80 characters, names the site and problem"},
        "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
        "summary": {"type": "string", "description": "2-4 sentences: what happened, how sure we are, what it costs"},
        "evidence": {"type": "array", "items": {"type": "string"}, "description": "Specific numbers from the data"},
        "likely_causes": {"type": "array", "items": {"type": "string"}, "description": "Most likely first"},
        "recommended_actions": {"type": "array", "items": {"type": "string"}, "description": "Ordered steps"},
        "parts_and_tools": {"type": "array", "items": {"type": "string"}},
        "safety_notes": {"type": "string"},
    },
    "required": ["title", "priority", "summary", "evidence", "likely_causes", "recommended_actions",
                 "parts_and_tools", "safety_notes"],
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def evidence_packet(event: dict, site: dict) -> dict:
    """Everything the drafter may use, and nothing else."""
    daily = event.get("evidence", {}).get("daily_pi", {})
    return {
        "site": {k: site.get(k) for k in ("system_id", "name", "location", "dc_capacity_kw", "mount",
                                           "tilt", "azimuth", "timezone")},
        "event": {k: event.get(k) for k in ("id", "kind", "label", "start", "end", "days", "active",
                                             "severity", "pi_before", "pi_during", "energy_lost_kwh",
                                             "est_cost_usd", "loss_pct")},
        "features": {k: v for k, v in event.get("evidence", {}).items() if k != "daily_pi"},
        "daily_pi_sample": dict(list(daily.items())[:10]),
        "playbook": PLAYBOOK.get(event["kind"], {}),
        "notes": "PI = actual energy / physics-expected energy from on-site irradiance and temperature. "
                 "~1.0 is healthy. est_cost_usd assumes $0.12/kWh.",
    }


def _evidence_lines(event: dict) -> list[str]:
    ev = event.get("evidence", {})
    lines = []
    if event.get("pi_before") is not None and event.get("pi_during") is not None:
        lines.append(f"Performance index fell from {event['pi_before']:.2f} in the two weeks before "
                     f"to a median of {event['pi_during']:.2f} during the event (1.00 = healthy).")
    elif event.get("pi_during") is not None:
        lines.append(f"Median performance index during the event: {event['pi_during']:.2f}.")
    if event.get("energy_lost_kwh"):
        lines.append(f"Estimated energy lost: {event['energy_lost_kwh']:,.0f} kWh "
                     f"({event.get('loss_pct') or 0:.0f}% of expected), about ${event['est_cost_usd']:,.0f}.")
    if ev.get("capacity_offline_pct") is not None:
        lines.append(f"Roughly {ev['capacity_offline_pct']:.0f}% of capacity appears offline, from the size of the step.")
    if ev.get("decline_began"):
        lines.append(f"The decline appears to have started around {ev['decline_began']}, "
                     f"{ev.get('decline_lead_days', '?')} days before it crossed the alert threshold.")
    if ev.get("recovered_to") is not None:
        lines.append(f"Performance recovered to {ev['recovered_to']:.2f} of baseline in the week after.")
    if ev.get("shape_gap") is not None and event["kind"] == "tracker_stall":
        lines.append(f"Morning and evening output ran {-100 * ev['shape_gap']:.0f} points further below "
                     "expectation than midday output.")
    if ev.get("plateau_frac") is not None and event["kind"] == "curtailment":
        lines.append(f"On clear days, output sat pinned at one level for {100 * ev['plateau_frac']:.0f}% of the "
                     "high-output hours while expected output kept rising above it.")
    if ev.get("poa_coverage") is not None:
        lines.append(f"Irradiance was recorded for only {100 * ev['poa_coverage']:.0f}% of producing intervals.")
    if ev.get("reason"):
        lines.append(ev["reason"])
    return lines


def template_ticket(event: dict, site: dict) -> dict:
    kind = event["kind"]
    status = "ongoing" if event.get("active") else f"{event['start']} to {event['end']}"
    pb = PLAYBOOK.get(kind, {"actions": [], "parts": []})
    cost = f" Estimated cost so far: ${event['est_cost_usd']:,.0f}." if event.get("est_cost_usd") else ""
    return _finish({
        "title": f"{site['name']}: {event['label'].lower()} ({status})",
        "priority": PRIORITY.get(event["severity"], "P3"),
        "summary": (f"{event['label']} detected at {site['name']} ({site['location']}) "
                    f"over {event['days']} day(s), {status}.{cost}"),
        "evidence": _evidence_lines(event),
        "likely_causes": _likely_causes(kind),
        "recommended_actions": pb["actions"],
        "parts_and_tools": pb["parts"],
        "safety_notes": "Follow site lockout/tagout and arc-flash procedures before opening any DC or AC enclosure.",
    }, event, drafted_by="template")


def _likely_causes(kind: str) -> list[str]:
    return {
        "outage": ["Inverter trip (ground fault, over-temperature, grid event)", "Opened AC breaker or disconnect",
                   "Utility grid outage"],
        "partial_outage": ["One inverter or inverter module offline", "Blown combiner fuse / open string",
                           "Tripped DC disconnect in one block"],
        "soiling": ["Dust or pollen build-up during a dry spell", "Bird droppings", "Gradual module degradation"],
        "curtailment": ["Utility export limit", "Inverter or plant-controller power setpoint",
                        "Inverter clipping from an incorrect AC rating setting"],
        "sensor_fault": ["Dirty or shaded pyranometer", "Sensor drift / out of calibration", "Sensor knocked out of plane"],
        "tracker_stall": ["Tracker controller fault or lost communications", "Stow mode left active after high wind",
                          "Failed drive motor or row power supply"],
        "data_gap": ["Data-logger power loss", "Network or cellular modem outage", "Logger storage full"],
    }.get(kind, [])


def _finish(body: dict, event: dict, drafted_by: str) -> dict:
    return {
        "ticket_id": f"T-{event['id']}",
        "event_id": event["id"],
        "site_id": event["site_id"],
        "kind": event["kind"],
        **body,
        "drafted_by": drafted_by,
        "drafted_at": _now(),
        "status": "pending_review",
    }


SYSTEM_PROMPT = """You are an operations & maintenance lead at a solar asset manager. You write maintenance \
tickets from monitoring evidence for a human dispatcher to approve.

Rules:
- Use only the numbers in the evidence packet. Never invent sensor readings, alarm codes, or dates.
- Say how confident the evidence is. A performance-index signature suggests a cause; it doesn't prove one.
- Actions must be ordered: cheapest remote checks first, then dispatch.
- Write for a field technician: plain, specific, no filler.
- If the event is ongoing, say so in the title."""


def claude_ticket(event: dict, site: dict, model: str | None = None, api_key: str | None = None,
                  client=None) -> dict:
    """Draft with Claude. Raises on failure; use `draft_ticket` for the safe version."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    model = model or os.environ.get("SOLARMON_MODEL", DEFAULT_MODEL)
    packet = evidence_packet(event, site)
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=[{"name": "draft_ticket", "description": "Submit the drafted maintenance ticket.",
                "input_schema": TICKET_SCHEMA}],
        tool_choice={"type": "tool", "name": "draft_ticket"},
        messages=[{"role": "user", "content":
                   "Draft a maintenance ticket for this event.\n\n<evidence>\n"
                   + json.dumps(packet, indent=2, default=str) + "\n</evidence>"}],
    )
    body = next(b.input for b in resp.content if getattr(b, "type", None) == "tool_use")
    missing = [k for k in TICKET_SCHEMA["required"] if k not in body]
    if missing:
        raise ValueError(f"Claude's draft is missing {missing}")
    return _finish(dict(body), event, drafted_by=f"claude:{model}")


def draft_ticket(event: dict, site: dict, use_claude: bool = False, **kw) -> dict:
    """Claude if asked and possible, otherwise (or on any error) the template."""
    if use_claude:
        try:
            return claude_ticket(event, site, **kw)
        except Exception as e:  # noqa: BLE001 - fall back, but say why
            t = template_ticket(event, site)
            t["draft_note"] = f"Claude draft failed ({type(e).__name__}: {e}); template used."
            return t
    return template_ticket(event, site)
