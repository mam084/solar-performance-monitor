"""Human review of draft tickets: approve, edit, or reject, with an audit trail.

Draft tickets come from the pipeline (data/processed/<id>/tickets.json) and never
change there. Reviewer decisions live beside them in decisions.json, keyed by
ticket_id, so a pipeline rebuild never wipes a decision and every change is logged.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("pending_review", "approved", "rejected")
EDITABLE = ("title", "priority", "summary", "recommended_actions", "parts_and_tools", "safety_notes")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_decisions(site_dir: Path) -> dict:
    return _read(site_dir / "decisions.json", {})


def load_tickets(site_dir: Path) -> list[dict]:
    """Draft tickets with any reviewer decisions and edits applied on top."""
    drafts = _read(site_dir / "tickets.json", [])
    decisions = load_decisions(site_dir)
    out = []
    for t in drafts:
        dec = decisions.get(t["ticket_id"])
        if dec:
            t = {**t, **dec.get("edits", {}), **dec.get("redraft", {}),
                 "status": dec["status"], "reviewer": dec.get("reviewer"),
                 "reviewed_at": dec.get("reviewed_at"), "review_note": dec.get("note"),
                 "history": dec.get("history", [])}
        out.append(t)
    return out


def record(site_dir: Path, ticket_id: str, status: str, reviewer: str = "", note: str = "",
           edits: dict | None = None, redraft: dict | None = None) -> dict:
    """Save a decision (or a redraft, keeping status pending) and append to its history."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if status == "rejected" and not note.strip():
        raise ValueError("A rejection needs a reason")
    edits = {k: v for k, v in (edits or {}).items() if k in EDITABLE}
    decisions = load_decisions(site_dir)
    prev = decisions.get(ticket_id, {})
    entry = {
        "status": status,
        "reviewer": reviewer or prev.get("reviewer") or "unknown",
        "reviewed_at": _now(),
        "note": note,
        "edits": {**prev.get("edits", {}), **edits},
        "redraft": redraft if redraft is not None else prev.get("redraft", {}),
        "history": prev.get("history", []) + [{
            "at": _now(), "status": status, "by": reviewer or "unknown", "note": note,
            "edited_fields": sorted(edits), "redrafted": redraft is not None,
        }],
    }
    decisions[ticket_id] = entry
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "decisions.json").write_text(json.dumps(decisions, indent=2) + "\n")
    return entry


def reset(site_dir: Path) -> None:
    """Clear all decisions for a site (drafts are untouched)."""
    (site_dir / "decisions.json").unlink(missing_ok=True)
