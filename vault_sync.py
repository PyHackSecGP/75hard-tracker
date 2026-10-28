"""CouchDB write-through for 75hard-tracker.

Writes daily snapshots and running logs to the brain LiveSync CouchDB. The
CouchDB endpoint lives on the brain LXC and is reached over Tailscale.

Fire-and-forget: failures are logged in the ``vault_sync_log`` SQLite table but
never block the UI.

Env vars (defaults match the brain deployment):

- ``BRAIN_URL`` — https://brain.taila06bcc.ts.net
- ``BRAIN_RESOLVE_IP`` — <brain-lxc-ip> (optional, used as a Host-header pin)
- ``BRAIN_DB`` — obsidian_brain
- ``BRAIN_USER`` — brain-admin
- ``BRAIN_PASS`` — CouchDB password (required to enable sync)
"""
from __future__ import annotations

import logging
import os
import socket
import threading
from typing import Callable
from urllib.parse import quote, urlparse

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

BRAIN_URL = os.environ.get("BRAIN_URL", "https://brain.taila06bcc.ts.net").rstrip("/")
BRAIN_DB = os.environ.get("BRAIN_DB", "obsidian_brain")
BRAIN_USER = os.environ.get("BRAIN_USER", "brain-admin")
BRAIN_PASS = os.environ.get("BRAIN_PASS", "")
BRAIN_RESOLVE_IP = os.environ.get("BRAIN_RESOLVE_IP", "").strip()
BRAIN_VERIFY_TLS = os.environ.get("BRAIN_VERIFY_TLS", "false").lower() == "true"

TIMEOUT = 10


def _install_resolve_pin() -> None:
    """Pin BRAIN hostname → BRAIN_RESOLVE_IP at the socket layer.

    Mirrors ``curl --resolve`` without touching ``/etc/hosts``. Idempotent;
    only wraps ``socket.getaddrinfo`` once per process.
    """
    if not BRAIN_RESOLVE_IP:
        return
    parsed = urlparse(BRAIN_URL)
    pin_host = parsed.hostname
    if not pin_host or getattr(socket, "_vault_sync_pinned", False):
        return
    original = socket.getaddrinfo

    def _patched(host, port, *args, **kwargs):
        if host == pin_host:
            return original(BRAIN_RESOLVE_IP, port, *args, **kwargs)
        return original(host, port, *args, **kwargs)

    socket.getaddrinfo = _patched  # type: ignore[assignment]
    socket._vault_sync_pinned = True  # type: ignore[attr-defined]


_install_resolve_pin()


def _session() -> requests.Session:
    s = requests.Session()
    s.auth = (BRAIN_USER, BRAIN_PASS)
    s.verify = BRAIN_VERIFY_TLS
    if not BRAIN_VERIFY_TLS:
        # Suppress noisy InsecureRequestWarning when we deliberately skip verify
        try:
            from urllib3 import disable_warnings
            from urllib3.exceptions import InsecureRequestWarning
            disable_warnings(InsecureRequestWarning)
        except Exception:
            pass
    return s


def _enabled() -> bool:
    return bool(BRAIN_PASS)


def _doc_url(doc_id: str) -> str:
    # CouchDB expects the whole doc id URL-encoded; LiveSync uses lowercased ids.
    return f"{BRAIN_URL}/{BRAIN_DB}/{quote(doc_id.lower(), safe='')}"


def _upsert(doc_id: str, body_markdown: str, extra_fields: dict) -> tuple[bool, str | None]:
    """Create or update a CouchDB doc. Returns (ok, rev)."""
    if not _enabled():
        return False, None
    doc_id = doc_id.lower()
    sess = _session()
    try:
        existing = sess.get(_doc_url(doc_id), timeout=TIMEOUT)
        payload: dict = {
            "_id": doc_id,
            # LiveSync-compatible plain note: single-chunk markdown in ``data``.
            "data": body_markdown,
            "ctime": extra_fields.get("ctime"),
            "mtime": extra_fields.get("mtime"),
            "size": len(body_markdown.encode("utf-8")),
            # Our own fields for find/query (ignored by Obsidian LiveSync).
            "body": body_markdown,
            **extra_fields,
        }
        if existing.status_code == 200:
            payload["_rev"] = existing.json()["_rev"]
        elif existing.status_code != 404:
            return False, f"get {existing.status_code}"
        resp = sess.put(_doc_url(doc_id), json=payload, timeout=TIMEOUT)
        if resp.status_code in (200, 201):
            return True, resp.json().get("rev")
        return False, f"put {resp.status_code} {resp.text[:120]}"
    except Exception as exc:  # noqa: BLE001 — fire-and-forget
        return False, str(exc)[:160]


def _render_daily(date_iso: str, data: dict) -> str:
    def row(label: str, value) -> str:
        return f"- **{label}:** {value}"

    streak = data.get("streak", 0)
    core = "✓" if data.get("core_complete") else "✗"

    hard_lines = [
        row("Diet",             "✓" if data.get("diet_followed") else "✗"),
        row("Workout 1",        f"{'✓' if data.get('workout1_done') else '✗'}  ({data.get('workout1_type') or '-'})"),
        row("Workout 2",        f"{'✓' if data.get('workout2_done') else '✗'}  outdoor={'✓' if data.get('workout2_outdoor') else '✗'}"),
        row("Water 4L",         "✓" if data.get("water_4l") else "✗"),
        row("Reading",          f"{'✓' if data.get('reading_done') else '✗'}  ({data.get('reading_pages') or 0} pages)"),
        row("Progress photo",   "✓" if data.get("progress_photo") else "✗"),
        row("Core complete",    core),
        row("Streak",           streak),
    ]

    metric_lines = [
        row("Weight (kg)",     data.get("weight_kg") or "-"),
        row("Steps",           data.get("steps") or 0),
        row("Pushups",         data.get("pushups") or 0),
        row("Situps",          data.get("situps") or 0),
        row("Squats",          data.get("squats") or 0),
        row("Calories today",  data.get("calories_today") or 0),
        row("Study hours",     data.get("study_hours") or 0),
        row("Spending (CAD)",  data.get("spending_total") or 0),
    ]

    sprint_lines = [f"- [{'x' if t['done'] else ' '}] {t['description']}"
                    for t in data.get("sprint_today", [])]
    marathon_lines = [f"- [{'x' if t['done'] else ' '}] {t['description']}"
                      for t in data.get("marathon_today", [])]
    log_lines = [f"> {ev}" for ev in data.get("log_events", [])]

    md = [
        f"# {date_iso}",
        "",
        "## 75 Hard",
        *hard_lines,
        "",
        "## Metrics",
        *metric_lines,
    ]
    if sprint_lines:
        md += ["", "## Sprint tasks today", *sprint_lines]
    if marathon_lines:
        md += ["", "## Marathon tasks today", *marathon_lines]
    if log_lines:
        md += ["", "## Log", *log_lines]
    return "\n".join(md) + "\n"


def _render_run(date_iso: str, run: dict) -> str:
    md = [
        f"# Run {date_iso}",
        "",
        f"- **Distance:** {run['distance_km']} km",
        f"- **Duration:** {run.get('duration_min') or '-'} min",
        f"- **Type:** {run.get('type') or 'easy'}",
        f"- **Avg HR:** {run.get('avg_hr') or '-'}",
    ]
    if run.get("notes"):
        md += ["", "## Notes", run["notes"]]
    return "\n".join(md) + "\n"


def _frontmatter(doc_type: str, extra: dict) -> dict:
    fm = {"type": doc_type}
    fm.update(extra)
    return fm


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


def sync_daily_async(date_iso: str, data: dict, record_result: Callable[[str, str | None, str], None]) -> None:
    """Fire-and-forget write of a daily tracker snapshot."""
    if not _enabled():
        return
    doc_id = f"20-areas/tracker/daily/{date_iso}.md"

    def _run() -> None:
        md = _render_daily(date_iso, data)
        extra = _frontmatter("tracker-daily", {"date": date_iso})
        ok, rev_or_err = _upsert(doc_id, md, extra)
        try:
            record_result(doc_id, rev_or_err if ok else None, "ok" if ok else f"fail:{rev_or_err}")
        except Exception:  # noqa: BLE001
            pass

    _spawn(_run)


def sync_run_async(date_iso: str, run: dict, record_result: Callable[[str, str | None, str], None]) -> None:
    """Fire-and-forget write of a single run log."""
    if not _enabled():
        return
    # Include seconds-ish suffix via run id so multiple runs per day don't clash
    suffix = run.get("id") or run.get("type") or "run"
    doc_id = f"20-areas/tracker/running/{date_iso}-{suffix}.md"

    def _run() -> None:
        md = _render_run(date_iso, run)
        extra = _frontmatter("tracker-run", {"date": date_iso, "distance_km": run["distance_km"]})
        ok, rev_or_err = _upsert(doc_id, md, extra)
        try:
            record_result(doc_id, rev_or_err if ok else None, "ok" if ok else f"fail:{rev_or_err}")
        except Exception:  # noqa: BLE001
            pass

    _spawn(_run)


def enabled() -> bool:
    """True if vault sync has credentials and will attempt writes."""
    return _enabled()
