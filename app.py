#!/usr/bin/env python3
"""75 Hard + sprint + marathon daily tracker — Flask app for GP Singh."""

import json
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

import tasks
import vault_sync

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "tracker.db"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_JSON_MODEL = os.environ.get("OLLAMA_JSON_MODEL", "llama3.2:3b")
START_WEIGHT = 135.0
GOAL_WEIGHT = 100.0
MARRIAGE_DATE = date(2026, 10, 16)   # 110 days from 2026-06-28
WEIGHT_START_DATE = date(2026, 6, 28)
CALORIE_TARGET = 1500

# Sprint + marathon windows (used to pick "today's phase")
SPRINT_START = date(2027, 1, 1)
PHASE_WINDOWS = [
    ("phase0", date(2026, 10, 27), date(2026, 12, 31)),
    ("phase1", date(2027, 1, 1),   date(2027, 1, 28)),
    ("phase2", date(2027, 1, 29),  date(2027, 3, 11)),
    ("phase3", date(2027, 3, 12),  date(2027, 5, 6)),
    ("phase4", date(2027, 5, 7),   date(2027, 6, 27)),
]
MARATHON_WINDOWS = [
    ("marathon_a", date(2026, 11, 1), date(2027, 1, 15)),
    ("marathon_b", date(2027, 1, 16), date(2027, 3, 11)),
    ("marathon_c", date(2027, 3, 12), date(2027, 4, 20)),
    ("marathon_d", date(2027, 4, 21), date(2027, 5, 2)),
]
MARATHON_RACE_DATE = date(2027, 5, 2)
SPRINT_END = date(2027, 6, 27)
BUDGET_MONTHLY_CAD = 1500


# ── database ──────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS checkins (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT UNIQUE NOT NULL,

            -- Core 75 Hard rules (all must be 1 for core_complete=1)
            diet_followed     INTEGER DEFAULT 0,
            workout1_done     INTEGER DEFAULT 0,
            workout1_type     TEXT    DEFAULT '',
            workout2_done     INTEGER DEFAULT 0,
            workout2_outdoor  INTEGER DEFAULT 0,
            water_4l          INTEGER DEFAULT 0,
            reading_done      INTEGER DEFAULT 0,
            reading_pages     INTEGER DEFAULT 0,
            progress_photo    INTEGER DEFAULT 0,

            -- Physical metrics
            steps             INTEGER DEFAULT 0,
            pushups           INTEGER DEFAULT 0,
            situps            INTEGER DEFAULT 0,
            squats            INTEGER DEFAULT 0,

            -- Wellness
            paath_done        INTEGER DEFAULT 0,
            kegels_done       INTEGER DEFAULT 0,
            skincare_done     INTEGER DEFAULT 0,
            haircare_done     INTEGER DEFAULT 0,

            -- Study
            study_hours       REAL    DEFAULT 0,
            study_notes_raw   TEXT    DEFAULT '',
            study_notes       TEXT    DEFAULT '',

            -- Spending
            money_spent       INTEGER DEFAULT 0,
            spending_raw      TEXT    DEFAULT '',
            spending_notes    TEXT    DEFAULT '',
            spending_total    REAL    DEFAULT 0,

            core_complete     INTEGER DEFAULT 0,
            created_at        TEXT    DEFAULT CURRENT_TIMESTAMP,
            updated_at        TEXT    DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS weight_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            weight_kg  REAL NOT NULL,
            notes      TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS projects (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            code         TEXT UNIQUE NOT NULL,
            name         TEXT NOT NULL,
            timeline     TEXT DEFAULT '',
            status       TEXT DEFAULT 'NOT STARTED',
            commits_week INTEGER DEFAULT 0,
            last_commit  TEXT DEFAULT '',
            updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS nutrition_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT NOT NULL,
            meal       TEXT DEFAULT '',
            description TEXT DEFAULT '',
            calories   INTEGER DEFAULT 0,
            protein_g  REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO projects (code, name, timeline) VALUES
            ('P1', 'SAST+DAST Triage Tool',       'Weeks 1-3'),
            ('P2', 'Threat Model Generator',       'Weeks 3-5'),
            ('P3', 'AI Log Anomaly Detector',      'Weeks 5-7'),
            ('P4', 'AI Pentest Report Assistant',  'Weeks 7-8');
    """)
    conn.commit()

    # Migrate checkins: add new columns to existing installs
    for col_def in [
        "calories_today INTEGER DEFAULT 0",
        "morning_cardio_type TEXT DEFAULT ''",
        "morning_cardio_minutes INTEGER DEFAULT 0",
        "evening_weights_done INTEGER DEFAULT 0",
        "evening_weights_notes TEXT DEFAULT ''",
    ]:
        try:
            conn.execute(f"ALTER TABLE checkins ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass

    # Migrate daily_log (older installs may already have the table)
    for col_def in [
        "status TEXT DEFAULT 'pending'",
        "parsed_at TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE daily_log ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass

    # v2 schema — sprint, marathon, daily log, running, targets, vault sync
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sprint_tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            track       TEXT NOT NULL,
            phase       TEXT NOT NULL,
            task_key    TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            due_week    INTEGER,
            done        INTEGER DEFAULT 0,
            done_date   TEXT    DEFAULT '',
            note        TEXT    DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS daily_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            raw_text    TEXT NOT NULL,
            parsed_json TEXT DEFAULT '',
            status      TEXT DEFAULT 'pending',   -- pending | parsed | failed
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            parsed_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS running_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT NOT NULL,
            distance_km  REAL NOT NULL,
            duration_min INTEGER DEFAULT 0,
            type         TEXT DEFAULT 'easy',
            avg_hr       INTEGER DEFAULT 0,
            notes        TEXT DEFAULT '',
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS daily_targets (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            key            TEXT UNIQUE NOT NULL,
            weekday_target REAL NOT NULL,
            weekend_target REAL,
            unit           TEXT,
            label          TEXT
        );

        CREATE TABLE IF NOT EXISTS vault_sync_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id    TEXT NOT NULL,
            rev       TEXT,
            synced_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status    TEXT
        );
    """)
    conn.commit()

    # Seed sprint/marathon tasks (upsert by task_key — descriptions stay editable)
    for t in tasks.TASKS:
        conn.execute(
            """INSERT INTO sprint_tasks (track, phase, task_key, description, due_week)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(task_key) DO UPDATE SET
                     track=excluded.track,
                     phase=excluded.phase,
                     description=excluded.description,
                     due_week=excluded.due_week""",
            (t["track"], t["phase"], t["task_key"], t["description"], t.get("due_week")),
        )

    # Seed daily targets (upsert by key)
    for key, wd, we, unit, label in tasks.DAILY_TARGETS:
        conn.execute(
            """INSERT INTO daily_targets (key, weekday_target, weekend_target, unit, label)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     weekday_target=excluded.weekday_target,
                     weekend_target=excluded.weekend_target,
                     unit=excluded.unit,
                     label=excluded.label""",
            (key, wd, we, unit, label),
        )

    conn.commit()
    conn.close()


# ── streak logic ──────────────────────────────────────────────────────────────

def get_streak() -> tuple[int, date | None]:
    """Return (streak_days, start_date) counting back from today."""
    conn = get_db()
    rows = conn.execute(
        "SELECT date FROM checkins WHERE core_complete=1 ORDER BY date DESC"
    ).fetchall()
    conn.close()

    if not rows:
        return 0, None

    streak = 0
    today = date.today()
    expected = today

    for row in rows:
        d = date.fromisoformat(row["date"])
        if d == today - timedelta(days=1) and streak == 0:
            streak += 1
            expected = d - timedelta(days=1)
        elif d == expected:
            streak += 1
            expected = d - timedelta(days=1)
        else:
            break

    start = date.fromisoformat(rows[streak - 1]["date"]) if streak else None
    return streak, start


def is_core_complete(data: dict) -> bool:
    return all([
        data.get("diet_followed"),
        data.get("workout1_done"),
        data.get("workout2_done"),
        data.get("workout2_outdoor"),
        data.get("water_4l"),
        data.get("reading_done"),
    ])


def marriage_stats(latest_weight: float) -> dict:
    today = date.today()
    days_left = max(0, (MARRIAGE_DATE - today).days)
    total_days = (MARRIAGE_DATE - WEIGHT_START_DATE).days
    elapsed = (today - WEIGHT_START_DATE).days
    kg_to_lose = round(latest_weight - GOAL_WEIGHT, 1)
    daily_rate = round(kg_to_lose / days_left, 3) if days_left > 0 else 0
    pct_elapsed = round(elapsed / total_days * 100, 1) if total_days > 0 else 0
    # Ideal weight today on the linear trajectory
    today_target = round(
        START_WEIGHT - (START_WEIGHT - GOAL_WEIGHT) * elapsed / total_days, 1
    ) if total_days > 0 else GOAL_WEIGHT
    on_track = latest_weight <= today_target
    return {
        "days_left": days_left,
        "kg_to_lose": kg_to_lose,
        "daily_rate_needed": daily_rate,
        "today_target": today_target,
        "on_track": on_track,
        "pct_elapsed": pct_elapsed,
        "marriage_date": MARRIAGE_DATE.isoformat(),
        "calorie_deficit_needed": round(daily_rate * 7700),
    }


# ── LLM helper ────────────────────────────────────────────────────────────────

def llm_format(system_prompt: str, raw: str) -> str:
    """Format raw text via Ollama. Returns raw on failure."""
    if not raw.strip():
        return raw
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"{system_prompt}\n\nInput: {raw}\n\nOutput:",
                "stream": False,
            },
            timeout=5,
        )
        if resp.ok:
            return resp.json().get("response", raw).strip()
    except Exception:
        pass
    return raw


def llm_json(prompt: str, timeout: int = 20) -> dict:
    """Request a JSON response from Ollama. Returns {} on any failure."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_JSON_MODEL,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            },
            timeout=timeout,
        )
        if not resp.ok:
            return {}
        payload = resp.json().get("response", "").strip()
        return json.loads(payload) if payload else {}
    except Exception:
        return {}


# Map common field name variants the LLM invents back to our schema.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "km":            ("km", "distance_km", "distance", "distance_m"),
    "duration_min":  ("duration_min", "duration", "duration_minutes", "minutes"),
    "avg_hr":        ("avg_hr", "heartrate", "heart_rate", "hr", "avg_heart_rate"),
    "type":          ("type", "workout", "run_type", "intensity"),
    "weight_kg":     ("weight_kg", "weight", "body_weight"),
    "reading_pages": ("reading_pages", "pages", "reading", "pages_read"),
    "pushups":       ("pushups", "push_ups"),
    "situps":        ("situps", "sit_ups"),
    "squats":        ("squats",),
    "steps":         ("steps",),
    "study_hours":   ("study_hours", "study", "study_time"),
    "water_L":       ("water_L", "water", "water_litres", "hydration", "hydration.water"),
}


def _flatten(d: dict, parent: str = "") -> dict:
    """Flatten a nested dict with dotted keys for simple alias matching."""
    out: dict = {}
    for k, v in d.items():
        nk = f"{parent}.{k}" if parent else k
        if isinstance(v, dict):
            out.update(_flatten(v, nk))
        else:
            out[nk] = v
    return out


def _coerce_num(v):
    """Coerce string numbers to int/float. Return None for junk/null."""
    if v is None or v == "" or v == "null":
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        s = str(v).strip().rstrip("kgmLh%,")
        f = float(s)
        return int(f) if f.is_integer() else f
    except (ValueError, TypeError):
        return None


def _normalize_parsed(raw: dict) -> dict:
    """Map LLM's free-form keys back to our schema and coerce string numbers."""
    if not isinstance(raw, dict) or not raw:
        return {}
    flat = _flatten(raw)
    index: dict[str, object] = {}
    for k, v in flat.items():
        index.setdefault(k.lower(), v)
        index.setdefault(k.split(".")[-1].lower(), v)

    numeric_keys = {"km", "duration_min", "avg_hr", "weight_kg", "reading_pages",
                    "pushups", "situps", "squats", "steps", "study_hours", "water_L"}

    out: dict = {}
    for canonical, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            v = index.get(alias.lower())
            if v in (None, "", [], {}, "null"):
                continue
            if canonical in numeric_keys:
                v = _coerce_num(v)
                if v is None:
                    continue
            out[canonical] = v
            break

    # Bundle running fields together when any of them is present
    run_keys = {"km", "duration_min", "avg_hr", "type"}
    if any(k in out for k in run_keys):
        out["running"] = {k: out.pop(k) for k in list(run_keys) if k in out}
        # Metres → km heuristic (LLMs sometimes return 6000 instead of 6)
        if (km := out["running"].get("km")) and isinstance(km, (int, float)) and km >= 200:
            out["running"]["km"] = round(km / 1000, 2)
        # Seconds → minutes heuristic (only for implausible run durations)
        if (dm := out["running"].get("duration_min")) and isinstance(dm, (int, float)) and dm > 500:
            out["running"]["duration_min"] = int(round(dm / 60))

    summary = index.get("summary") or index.get("note") or index.get("notes") or ""
    if summary:
        out["summary"] = str(summary)[:200]
    return out


# ── vault sync bridge ─────────────────────────────────────────────────────────

def _record_vault_result(doc_id: str, rev: str | None, status: str) -> None:
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO vault_sync_log (doc_id, rev, status) VALUES (?, ?, ?)",
            (doc_id, rev or "", status),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _collect_daily_snapshot(day_iso: str) -> dict:
    """Build the dict passed to vault_sync.sync_daily_async for ``day_iso``."""
    conn = get_db()
    row = conn.execute("SELECT * FROM checkins WHERE date=?", (day_iso,)).fetchone()
    weight = conn.execute(
        "SELECT weight_kg FROM weight_log WHERE date=? ORDER BY id DESC LIMIT 1",
        (day_iso,),
    ).fetchone()
    streak, _ = get_streak()

    sprint_today = [dict(r) for r in conn.execute(
        """SELECT task_key, description, done FROM sprint_tasks
           WHERE track='sprint' AND phase=? ORDER BY id""",
        (_current_phase("sprint"),),
    ).fetchall()][:8]
    marathon_today = [dict(r) for r in conn.execute(
        """SELECT task_key, description, done FROM sprint_tasks
           WHERE track='marathon' AND phase=? ORDER BY id""",
        (_current_phase("marathon"),),
    ).fetchall()][:8]
    log_events = [r["raw_text"] for r in conn.execute(
        "SELECT raw_text FROM daily_log WHERE date=? ORDER BY id DESC LIMIT 5", (day_iso,),
    ).fetchall()]
    conn.close()

    data = dict(row) if row else {"date": day_iso}
    data["streak"] = streak
    data["weight_kg"] = weight["weight_kg"] if weight else None
    data["sprint_today"] = sprint_today
    data["marathon_today"] = marathon_today
    data["log_events"] = log_events
    return data


def _sync_today_to_vault() -> None:
    today = date.today().isoformat()
    vault_sync.sync_daily_async(today, _collect_daily_snapshot(today), _record_vault_result)


# ── sprint / marathon helpers ─────────────────────────────────────────────────

def _current_phase(track: str) -> str:
    today = date.today()
    windows = PHASE_WINDOWS if track == "sprint" else MARATHON_WINDOWS
    for key, start, end in windows:
        if start <= today <= end:
            return key
    # Default to the next upcoming window
    for key, start, _ in windows:
        if today < start:
            return key
    return windows[-1][0]


def _progress_pct(current: float, target: float) -> int:
    if target <= 0:
        return 0
    return int(max(0, min(100, round(current / target * 100))))


def _marathon_week_km() -> tuple[float, float]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(distance_km), 0) AS km FROM running_log WHERE date >= ?",
        (week_start.isoformat(),),
    ).fetchone()
    conn.close()
    km = float(row["km"] or 0)
    target = tasks.MARATHON_WEEKLY_KM.get(_current_phase("marathon"), 20)
    return km, float(target)


def _phase_progress(track: str, phase: str) -> tuple[int, int]:
    conn = get_db()
    row = conn.execute(
        """SELECT
               SUM(CASE WHEN done=1 THEN 1 ELSE 0 END) AS d,
               COUNT(*) AS t
             FROM sprint_tasks WHERE track=? AND phase=?""",
        (track, phase),
    ).fetchone()
    conn.close()
    return int(row["d"] or 0), int(row["t"] or 0)


def _streak_segments(limit: int = 14) -> list[dict]:
    """Return the last ``limit`` days with core_complete flags for a visual bar."""
    conn = get_db()
    rows = {
        r["date"]: int(r["core_complete"] or 0)
        for r in conn.execute(
            "SELECT date, core_complete FROM checkins ORDER BY date DESC LIMIT ?",
            (limit * 2,),
        ).fetchall()
    }
    conn.close()
    today = date.today()
    segs = []
    for i in range(limit - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        segs.append({"date": d, "complete": rows.get(d, 0)})
    return segs


def _study_target_today() -> float:
    return 8.0 if date.today().weekday() >= 5 else 3.0


def _monthly_spending_total() -> float:
    first_of_month = date.today().replace(day=1).isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(spending_total), 0) AS t FROM checkins WHERE date >= ?",
        (first_of_month,),
    ).fetchone()
    conn.close()
    return float(row["t"] or 0)


# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    conn = get_db()
    today = date.today().isoformat()

    today_row = conn.execute(
        "SELECT * FROM checkins WHERE date=?", (today,)
    ).fetchone()

    streak, streak_start = get_streak()

    weights = conn.execute(
        "SELECT date, weight_kg FROM weight_log ORDER BY date DESC, id DESC LIMIT 1"
    ).fetchone()
    latest_weight = weights["weight_kg"] if weights else START_WEIGHT

    projects = conn.execute("SELECT * FROM projects ORDER BY code").fetchall()

    history = conn.execute(
        "SELECT date, core_complete FROM checkins ORDER BY date DESC LIMIT 10"
    ).fetchall()

    # Calories today from checkin or nutrition_log (whichever is higher)
    cals_row = conn.execute(
        "SELECT COALESCE(SUM(calories), 0) as total FROM nutrition_log WHERE date=?", (today,)
    ).fetchone()
    calories_today = cals_row["total"] if cals_row else 0
    if today_row and today_row["calories_today"]:
        calories_today = max(calories_today, today_row["calories_today"])

    # Weight chart data
    weight_rows = [
        {"date": r[0], "weight_kg": r[1]}
        for r in conn.execute(
            "SELECT date, weight_kg FROM weight_log ORDER BY date ASC LIMIT 90"
        ).fetchall()
    ]

    # Sprint + marathon today (reuse the open connection before close)
    sprint_phase = _current_phase("sprint")
    marathon_phase = _current_phase("marathon")
    sprint_today = [dict(r) for r in conn.execute(
        """SELECT id, task_key, description, done FROM sprint_tasks
           WHERE track='sprint' AND phase=? ORDER BY done, id LIMIT 5""", (sprint_phase,),
    ).fetchall()]
    marathon_today = [dict(r) for r in conn.execute(
        """SELECT id, task_key, description, done FROM sprint_tasks
           WHERE track='marathon' AND phase=? ORDER BY done, id LIMIT 5""", (marathon_phase,),
    ).fetchall()]
    log_events = [dict(r) for r in conn.execute(
        "SELECT date, raw_text, parsed_json, status FROM daily_log ORDER BY id DESC LIMIT 5"
    ).fetchall()]

    conn.close()

    # Target trajectory for dashboard chart
    total_days = (MARRIAGE_DATE - WEIGHT_START_DATE).days
    target_line = [
        {
            "date": (WEIGHT_START_DATE + timedelta(days=i)).isoformat(),
            "target": round(START_WEIGHT - (START_WEIGHT - GOAL_WEIGHT) * i / total_days, 1),
        }
        for i in range(0, total_days + 1, 3)
    ]

    m = marriage_stats(latest_weight)

    sprint_done, sprint_total = _phase_progress("sprint", sprint_phase)
    marathon_done, marathon_total = _phase_progress("marathon", marathon_phase)
    week_km, week_target = _marathon_week_km()

    # Progress bar values for the metrics card
    study_hours = (today_row["study_hours"] if today_row else 0) or 0
    study_target = _study_target_today()
    water_L = 4.0 if (today_row and today_row["water_4l"]) else 0.0
    steps = (today_row["steps"] if today_row else 0) or 0
    steps_target = 15000 if date.today().weekday() >= 5 else 10000
    reading_pages = (today_row["reading_pages"] if today_row else 0) or 0
    pushups = (today_row["pushups"] if today_row else 0) or 0
    pushups_target = 100 if date.today().weekday() >= 5 else 50
    monthly_spent = _monthly_spending_total()

    streak_bar = _streak_segments(14)

    bars = {
        "weight":   {"pct": round(max(0, (START_WEIGHT - latest_weight) / (START_WEIGHT - GOAL_WEIGHT) * 100), 1),
                     "label": f"{latest_weight} / {GOAL_WEIGHT} kg", "sub": f"{round(latest_weight - GOAL_WEIGHT, 1)} kg to go"},
        "study":    {"pct": _progress_pct(study_hours, study_target),
                     "label": f"{study_hours}h / {study_target}h", "sub": "today"},
        "water":    {"pct": _progress_pct(water_L, 4.0),
                     "label": f"{water_L:.1f}L / 4.0L", "sub": "today"},
        "steps":    {"pct": _progress_pct(steps, steps_target),
                     "label": f"{steps:,} / {steps_target:,}", "sub": "today"},
        "reading":  {"pct": _progress_pct(reading_pages, 10),
                     "label": f"{reading_pages} / 10 pages", "sub": "today"},
        "pushups":  {"pct": _progress_pct(pushups, pushups_target),
                     "label": f"{pushups} / {pushups_target}", "sub": "today"},
        "sprint":   {"pct": _progress_pct(sprint_done, sprint_total or 1),
                     "label": f"{sprint_done} / {sprint_total}", "sub": tasks.PHASE_META[sprint_phase]["label"]},
        "marathon": {"pct": _progress_pct(marathon_done, marathon_total or 1),
                     "label": f"{marathon_done} / {marathon_total}", "sub": tasks.PHASE_META[marathon_phase]["label"]},
        "week_km":  {"pct": _progress_pct(week_km, week_target),
                     "label": f"{week_km:.1f} / {week_target} km", "sub": "this week"},
        "spending": {"pct": _progress_pct(monthly_spent, BUDGET_MONTHLY_CAD),
                     "label": f"${monthly_spent:,.0f} / ${BUDGET_MONTHLY_CAD:,}", "sub": "this month"},
    }

    return render_template("dashboard.html",
        today=today,
        today_row=today_row,
        streak=streak,
        streak_start=streak_start,
        streak_bar=streak_bar,
        latest_weight=latest_weight,
        weight_lost=round(START_WEIGHT - latest_weight, 1),
        weight_to_go=round(latest_weight - GOAL_WEIGHT, 1),
        goal_weight=GOAL_WEIGHT,
        start_weight=START_WEIGHT,
        weight_pct=round(max(0, (START_WEIGHT - latest_weight) / (START_WEIGHT - GOAL_WEIGHT) * 100), 1),
        history=history,
        # marriage
        days_to_marriage=m["days_left"],
        kg_to_lose=m["kg_to_lose"],
        daily_rate_needed=m["daily_rate_needed"],
        today_target=m["today_target"],
        on_track=m["on_track"],
        marriage_date=m["marriage_date"],
        deficit_needed=m["calorie_deficit_needed"],
        # nutrition
        calories_today=calories_today,
        calorie_target=CALORIE_TARGET,
        # chart
        weight_chart=weight_rows,
        target_line=target_line,
        # new
        sprint_today=sprint_today,
        marathon_today=marathon_today,
        sprint_phase_label=tasks.PHASE_META[sprint_phase]["label"],
        marathon_phase_label=tasks.PHASE_META[marathon_phase]["label"],
        bars=bars,
        log_events=log_events,
        vault_enabled=vault_sync.enabled(),
    )


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    today = date.today().isoformat()
    is_weekend = date.today().weekday() >= 5
    study_target = 8 if is_weekend else 3

    if request.method == "POST":
        f = request.form

        study_raw = f.get("study_notes_raw", "")
        study_notes = llm_format(
            "You are a concise note-formatter. Rewrite these raw study notes as a "
            "clean 2-4 line structured summary: topic covered, key takeaways, "
            "any resources used. Plain text, no markdown headers.",
            study_raw,
        )

        spending_raw = f.get("spending_raw", "")
        spending_notes = llm_format(
            "You are a personal finance logger. Rewrite this spending description "
            "as a clean bullet list with: item, category, and CAD amount. "
            "Add a Total line at the end. Plain text only.",
            spending_raw,
        )

        data = {
            "date": today,
            "diet_followed":          1 if f.get("diet_followed")        else 0,
            "workout1_done":          1 if f.get("workout1_done")         else 0,
            "workout1_type":          f.get("workout1_type", ""),
            "workout2_done":          1 if f.get("workout2_done")         else 0,
            "workout2_outdoor":       1 if f.get("workout2_outdoor")      else 0,
            "water_4l":               1 if f.get("water_4l")              else 0,
            "reading_done":           1 if f.get("reading_done")          else 0,
            "reading_pages":          int(f.get("reading_pages") or 0),
            "progress_photo":         1 if f.get("progress_photo")        else 0,
            "steps":                  int(f.get("steps") or 0),
            "pushups":                int(f.get("pushups") or 0),
            "situps":                 int(f.get("situps") or 0),
            "squats":                 int(f.get("squats") or 0),
            "paath_done":             1 if f.get("paath_done")            else 0,
            "kegels_done":            1 if f.get("kegels_done")           else 0,
            "skincare_done":          1 if f.get("skincare_done")         else 0,
            "haircare_done":          1 if f.get("haircare_done")         else 0,
            "study_hours":            float(f.get("study_hours") or 0),
            "study_notes_raw":        study_raw,
            "study_notes":            study_notes,
            "money_spent":            1 if f.get("money_spent")           else 0,
            "spending_raw":           spending_raw,
            "spending_notes":         spending_notes,
            "spending_total":         float(f.get("spending_total") or 0),
            # nutrition / fitness
            "calories_today":         int(f.get("calories_today") or 0),
            "morning_cardio_type":    f.get("morning_cardio_type", ""),
            "morning_cardio_minutes": int(f.get("morning_cardio_minutes") or 0),
            "evening_weights_done":   1 if f.get("evening_weights_done")  else 0,
            "evening_weights_notes":  f.get("evening_weights_notes", ""),
        }
        data["core_complete"] = 1 if is_core_complete(data) else 0

        conn = get_db()
        conn.execute("""
            INSERT INTO checkins (
                date, diet_followed, workout1_done, workout1_type,
                workout2_done, workout2_outdoor, water_4l, reading_done,
                reading_pages, progress_photo, steps, pushups, situps,
                squats, paath_done, kegels_done, skincare_done, haircare_done,
                study_hours, study_notes_raw, study_notes, money_spent,
                spending_raw, spending_notes, spending_total, core_complete,
                calories_today, morning_cardio_type, morning_cardio_minutes,
                evening_weights_done, evening_weights_notes
            ) VALUES (
                :date, :diet_followed, :workout1_done, :workout1_type,
                :workout2_done, :workout2_outdoor, :water_4l, :reading_done,
                :reading_pages, :progress_photo, :steps, :pushups, :situps,
                :squats, :paath_done, :kegels_done, :skincare_done, :haircare_done,
                :study_hours, :study_notes_raw, :study_notes, :money_spent,
                :spending_raw, :spending_notes, :spending_total, :core_complete,
                :calories_today, :morning_cardio_type, :morning_cardio_minutes,
                :evening_weights_done, :evening_weights_notes
            ) ON CONFLICT(date) DO UPDATE SET
                diet_followed=excluded.diet_followed,
                workout1_done=excluded.workout1_done,
                workout1_type=excluded.workout1_type,
                workout2_done=excluded.workout2_done,
                workout2_outdoor=excluded.workout2_outdoor,
                water_4l=excluded.water_4l,
                reading_done=excluded.reading_done,
                reading_pages=excluded.reading_pages,
                progress_photo=excluded.progress_photo,
                steps=excluded.steps,
                pushups=excluded.pushups,
                situps=excluded.situps,
                squats=excluded.squats,
                paath_done=excluded.paath_done,
                kegels_done=excluded.kegels_done,
                skincare_done=excluded.skincare_done,
                haircare_done=excluded.haircare_done,
                study_hours=excluded.study_hours,
                study_notes_raw=excluded.study_notes_raw,
                study_notes=excluded.study_notes,
                money_spent=excluded.money_spent,
                spending_raw=excluded.spending_raw,
                spending_notes=excluded.spending_notes,
                spending_total=excluded.spending_total,
                core_complete=excluded.core_complete,
                calories_today=excluded.calories_today,
                morning_cardio_type=excluded.morning_cardio_type,
                morning_cardio_minutes=excluded.morning_cardio_minutes,
                evening_weights_done=excluded.evening_weights_done,
                evening_weights_notes=excluded.evening_weights_notes,
                updated_at=CURRENT_TIMESTAMP
        """, data)
        conn.commit()
        conn.close()
        _sync_today_to_vault()
        return redirect(url_for("dashboard"))

    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM checkins WHERE date=?", (today,)
    ).fetchone()
    conn.close()

    return render_template("checkin.html",
        today=today,
        existing=existing,
        study_target=study_target,
        is_weekend=is_weekend,
        calorie_target=CALORIE_TARGET,
    )


@app.route("/weight", methods=["GET", "POST"])
def weight():
    conn = get_db()

    if request.method == "POST":
        w = float(request.form.get("weight_kg", 0))
        notes = request.form.get("notes", "")
        conn.execute(
            "INSERT INTO weight_log (date, weight_kg, notes) VALUES (?, ?, ?)",
            (date.today().isoformat(), w, notes),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("weight"))

    rows = conn.execute(
        "SELECT date, weight_kg, notes FROM weight_log ORDER BY date DESC, id DESC LIMIT 90"
    ).fetchall()
    conn.close()

    chart_data = json.dumps([
        {"date": r["date"], "weight": r["weight_kg"]}
        for r in reversed(rows)
    ])

    # Target trajectory: linear 135 → 100 over 110 days
    total_days = (MARRIAGE_DATE - WEIGHT_START_DATE).days
    target_line = json.dumps([
        {
            "date": (WEIGHT_START_DATE + timedelta(days=i)).isoformat(),
            "target": round(START_WEIGHT - (START_WEIGHT - GOAL_WEIGHT) * i / total_days, 1),
        }
        for i in range(0, total_days + 1, 3)  # every 3 days to keep payload small
    ])

    latest = rows[0]["weight_kg"] if rows else START_WEIGHT
    m = marriage_stats(latest)
    behind_by = round(latest - m["today_target"], 1)  # positive = behind, negative = ahead

    return render_template("weight.html",
        rows=rows,
        chart_data=chart_data,
        target_line=target_line,
        goal_weight=GOAL_WEIGHT,
        start_weight=START_WEIGHT,
        marriage_date=MARRIAGE_DATE.isoformat(),
        today_target=m["today_target"],
        on_track=m["on_track"],
        days_left=m["days_left"],
        latest_weight=latest,
        behind_by=behind_by,
        kg_to_lose=m["kg_to_lose"],
        daily_rate_needed=m["daily_rate_needed"],
    )


@app.route("/nutrition", methods=["GET", "POST"])
def nutrition():
    conn = get_db()
    today = date.today().isoformat()

    if request.method == "POST":
        conn.execute(
            """INSERT INTO nutrition_log (date, meal, description, calories, protein_g)
               VALUES (?, ?, ?, ?, ?)""",
            (
                today,
                request.form.get("meal", ""),
                request.form.get("description", ""),
                int(request.form.get("calories") or 0),
                float(request.form.get("protein_g") or 0),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("nutrition"))

    today_meals = conn.execute(
        "SELECT * FROM nutrition_log WHERE date=? ORDER BY created_at", (today,)
    ).fetchall()
    today_calories = sum(r["calories"] for r in today_meals)
    today_protein = round(sum(r["protein_g"] for r in today_meals), 1)

    recent = conn.execute(
        "SELECT date, SUM(calories) as total_cal, SUM(protein_g) as total_prot "
        "FROM nutrition_log GROUP BY date ORDER BY date DESC LIMIT 14"
    ).fetchall()

    conn.close()

    return render_template("nutrition.html",
        today=today,
        today_meals=today_meals,
        today_calories=today_calories,
        today_protein=today_protein,
        calorie_target=CALORIE_TARGET,
        protein_target=175,  # ~1.3g per kg of goal body weight
        recent=recent,
    )


@app.route("/nutrition/delete/<int:meal_id>", methods=["POST"])
def nutrition_delete(meal_id: int):
    conn = get_db()
    conn.execute("DELETE FROM nutrition_log WHERE id=?", (meal_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("nutrition"))


@app.route("/history")
def history():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM checkins ORDER BY date DESC LIMIT 75"
    ).fetchall()
    conn.close()
    return render_template("history.html", rows=rows)


@app.route("/projects", methods=["GET", "POST"])
def projects():
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            """UPDATE projects
               SET status=?, commits_week=?, last_commit=?, updated_at=CURRENT_TIMESTAMP
               WHERE code=?""",
            (
                request.form.get("status"),
                int(request.form.get("commits_week") or 0),
                request.form.get("last_commit", ""),
                request.form.get("code"),
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("projects"))

    rows = conn.execute("SELECT * FROM projects ORDER BY code").fetchall()
    conn.close()
    return render_template("projects.html", projects=rows)


@app.route("/api/format", methods=["POST"])
def api_format():
    """AJAX endpoint — LLM-format raw text on the check-in page."""
    data = request.get_json()
    kind = data.get("type", "study")

    if kind == "study":
        prompt = (
            "Rewrite these raw study notes as a clean 2-4 line summary: "
            "topic, key takeaways, resources used. Plain text, no headers."
        )
    else:
        prompt = (
            "Rewrite this spending log as a clean bullet list: item, category, CAD amount. "
            "Add a Total line. Plain text only."
        )

    formatted = llm_format(prompt, data.get("text", ""))
    return jsonify({"formatted": formatted})


@app.route("/api/state")
def api_state():
    """Machine-readable state for update-agent.py."""
    streak, start = get_streak()
    conn = get_db()
    w = conn.execute(
        "SELECT weight_kg FROM weight_log ORDER BY date DESC, id DESC LIMIT 1"
    ).fetchone()
    projects = [dict(r) for r in conn.execute(
        "SELECT * FROM projects ORDER BY code"
    ).fetchall()]
    conn.close()

    latest = w["weight_kg"] if w else START_WEIGHT
    m = marriage_stats(latest)

    return jsonify({
        "75hard_day": streak,
        "75hard_start": start.isoformat() if start else None,
        "weight_kg": latest,
        "marriage": m,
        "projects": projects,
        "updated_at": datetime.now().isoformat(),
    })


# ── sprint + marathon routes ──────────────────────────────────────────────────

@app.route("/sprint")
def sprint_board():
    conn = get_db()
    all_tasks = [dict(r) for r in conn.execute(
        "SELECT * FROM sprint_tasks ORDER BY phase, done, id"
    ).fetchall()]
    conn.close()

    grouped: dict[str, dict] = {}
    for t in all_tasks:
        g = grouped.setdefault(t["phase"], {
            "phase": t["phase"],
            "meta": tasks.PHASE_META.get(t["phase"], {"label": t["phase"], "order": 99, "track": t["track"]}),
            "tasks": [],
            "done": 0,
            "total": 0,
        })
        g["tasks"].append(t)
        g["total"] += 1
        g["done"] += 1 if t["done"] else 0
    for g in grouped.values():
        g["pct"] = _progress_pct(g["done"], g["total"] or 1)

    ordered = sorted(grouped.values(), key=lambda x: x["meta"].get("order", 99))
    current_sprint_phase = _current_phase("sprint")
    current_marathon_phase = _current_phase("marathon")

    return render_template("sprint.html",
        groups=ordered,
        current_sprint_phase=current_sprint_phase,
        current_marathon_phase=current_marathon_phase,
    )


@app.route("/sprint/tick/<task_key>", methods=["POST"])
def sprint_tick(task_key: str):
    conn = get_db()
    row = conn.execute(
        "SELECT done FROM sprint_tasks WHERE task_key=?", (task_key,)
    ).fetchone()
    if row is None:
        conn.close()
        return jsonify({"ok": False, "error": "unknown task"}), 404
    new_done = 0 if row["done"] else 1
    done_date = date.today().isoformat() if new_done else ""
    conn.execute(
        "UPDATE sprint_tasks SET done=?, done_date=? WHERE task_key=?",
        (new_done, done_date, task_key),
    )
    conn.commit()
    conn.close()
    _sync_today_to_vault()
    if request.headers.get("HX-Request"):
        state = "done" if new_done else "open"
        return f'<span class="task-state {state}" data-key="{task_key}">{state}</span>'
    return jsonify({"ok": True, "done": bool(new_done)})


@app.route("/sprint/log", methods=["POST"])
def sprint_log():
    """Save raw log immediately. LLM parses async in background."""
    text = (request.form.get("text") or (request.json or {}).get("text") if request.is_json else request.form.get("text")) or ""
    text = text.strip()
    if not text:
        return redirect(url_for("dashboard"))

    today_iso = date.today().isoformat()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO daily_log (date, raw_text, status) VALUES (?, ?, 'pending')",
        (today_iso, text),
    )
    log_id = cur.lastrowid
    conn.commit()
    conn.close()

    _spawn_parse(log_id, text, today_iso)
    _sync_today_to_vault()

    if request.headers.get("HX-Request"):
        return render_template("_log_result.html",
            parsed={},
            tasks_done=[],
            summary="Queued — AI is parsing in background. Refresh in ~30s.",
        )
    return redirect(url_for("dashboard"))


def _spawn_parse(log_id: int, text: str, today_iso: str) -> None:
    def _work() -> None:
        try:
            _parse_and_apply(log_id, text, today_iso)
        except Exception:  # noqa: BLE001 — background, log via vault_sync table
            try:
                conn = get_db()
                conn.execute(
                    "UPDATE daily_log SET status='failed', parsed_at=CURRENT_TIMESTAMP WHERE id=?",
                    (log_id,),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
    threading.Thread(target=_work, daemon=True).start()


def _parse_and_apply(log_id: int, text: str, today_iso: str) -> None:
    """Parse the entry: small LLM call for structured fields, keyword match for tasks.

    Keeping the LLM prompt tiny (no task catalog) lets a 3B model respond in
    seconds instead of minutes. Task matches happen deterministically in
    Python against the current-phase task descriptions.
    """
    conn = get_db()
    task_rows = [dict(r) for r in conn.execute(
        """SELECT task_key, description FROM sprint_tasks
           WHERE done=0 AND phase IN (?, ?, 'prep')""",
        (_current_phase("sprint"), _current_phase("marathon")),
    ).fetchall()]
    conn.close()

    prompt = f"""Extract structured data from a short daily log entry. Return JSON only.

Fields (omit any that are not clearly in the entry):
- running: {{"km": number, "type": "easy|tempo|long|race|strength", "duration_min": number, "avg_hr": number}}
- weight_kg: number
- reading_pages: integer
- pushups: integer
- situps: integer
- squats: integer
- steps: integer
- study_hours: number
- water_L: number (how many litres of water)
- summary: one short sentence

Entry: {text}

JSON:"""
    raw = llm_json(prompt, timeout=210)
    parsed = _normalize_parsed(raw)

    # Keyword-match sprint/marathon tasks against the raw text (case-insensitive).
    text_lower = text.lower()
    tasks_done = []
    for row in task_rows:
        key = row["task_key"].lower()
        desc_words = [w for w in row["description"].lower().replace(",", " ").split() if len(w) > 3]
        # Match if the task_key appears verbatim, or 2+ meaningful words from the description do.
        if key in text_lower:
            tasks_done.append(row["task_key"])
            continue
        hits = sum(1 for w in desc_words if w in text_lower)
        if hits >= 3:
            tasks_done.append(row["task_key"])

    # Derive streak hits deterministically from parsed numbers + regex hints.
    streaks = set()
    if parsed.get("water_L") is not None and float(parsed["water_L"]) >= 4:
        streaks.add("water_4l")
    if parsed.get("reading_pages") and int(parsed["reading_pages"]) >= 5:
        streaks.add("reading_done")
    low = text_lower
    if "diet" in low or "fasted" in low or "on plan" in low or "stayed on plan" in low:
        streaks.add("diet_followed")
    if "progress photo" in low or "photo" in low:
        streaks.add("progress_photo")
    if "paath" in low or "nitnem" in low or "prayer" in low:
        streaks.add("paath_done")
    if parsed.get("running") or any(w in low for w in ["workout", "gym", "lifted", "ran", "run "]):
        streaks.add("workout1_done")
    if "outdoor" in low and any(w in low for w in ["ran", "run ", "walked", "walk ", "hike", "biked"]):
        streaks.add("workout2_done")
        streaks.add("workout2_outdoor")

    conn = get_db()
    for key in tasks_done:
        conn.execute(
            "UPDATE sprint_tasks SET done=1, done_date=? WHERE task_key=? AND done=0",
            (today_iso, key),
        )

    valid_fields = {"diet_followed", "workout1_done", "workout2_done", "workout2_outdoor",
                    "water_4l", "reading_done", "progress_photo", "paath_done",
                    "kegels_done", "skincare_done", "haircare_done"}
    streaks &= valid_fields
    if streaks:
        conn.execute("INSERT INTO checkins (date) VALUES (?) ON CONFLICT(date) DO NOTHING", (today_iso,))
        conn.execute(
            f"UPDATE checkins SET {', '.join(f + '=1' for f in streaks)}, updated_at=CURRENT_TIMESTAMP WHERE date=?",
            (today_iso,),
        )
        row = conn.execute("SELECT * FROM checkins WHERE date=?", (today_iso,)).fetchone()
        if row:
            conn.execute(
                "UPDATE checkins SET core_complete=? WHERE date=?",
                (1 if is_core_complete(dict(row)) else 0, today_iso),
            )

    numeric_cols = {"reading_pages", "pushups", "situps", "squats", "steps", "study_hours"}
    num_updates, num_values = [], []
    for k in numeric_cols:
        if parsed.get(k) is not None:
            num_updates.append(f"{k}=?")
            num_values.append(parsed[k])
    if num_updates:
        conn.execute("INSERT INTO checkins (date) VALUES (?) ON CONFLICT(date) DO NOTHING", (today_iso,))
        conn.execute(
            f"UPDATE checkins SET {', '.join(num_updates)}, updated_at=CURRENT_TIMESTAMP WHERE date=?",
            tuple(num_values) + (today_iso,),
        )

    if parsed.get("weight_kg"):
        conn.execute(
            "INSERT INTO weight_log (date, weight_kg, notes) VALUES (?, ?, ?)",
            (today_iso, float(parsed["weight_kg"]), "logged via /sprint/log"),
        )

    run_info = parsed.get("running") or {}
    run_id = None
    if run_info and run_info.get("km"):
        cur = conn.execute(
            """INSERT INTO running_log (date, distance_km, duration_min, type, avg_hr, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
            (
                today_iso,
                float(run_info["km"]),
                int(run_info.get("duration_min") or 0),
                run_info.get("type") or "easy",
                int(run_info.get("avg_hr") or 0),
                parsed.get("summary", ""),
            ),
        )
        run_id = cur.lastrowid

    # Record what we applied so the UI can show it, even if the LLM returned nothing.
    applied = {
        **(parsed or {}),
        "tasks_done": tasks_done,
        "streaks_hit": sorted(streaks),
    }
    status = "parsed" if (parsed or tasks_done or streaks) else "failed"
    conn.execute(
        "UPDATE daily_log SET parsed_json=?, status=?, parsed_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(applied), status, log_id),
    )
    conn.commit()
    conn.close()

    if run_id and run_info.get("km"):
        vault_sync.sync_run_async(
            today_iso,
            {
                "id": run_id,
                "distance_km": float(run_info["km"]),
                "duration_min": int(run_info.get("duration_min") or 0),
                "type": run_info.get("type") or "easy",
                "avg_hr": int(run_info.get("avg_hr") or 0),
                "notes": parsed.get("summary", ""),
            },
            _record_vault_result,
        )
    _sync_today_to_vault()


@app.route("/running", methods=["GET", "POST"])
def running():
    conn = get_db()
    if request.method == "POST":
        km = float(request.form.get("distance_km", 0) or 0)
        if km <= 0:
            conn.close()
            return redirect(url_for("running"))
        duration = int(request.form.get("duration_min", 0) or 0)
        run_type = request.form.get("type", "easy")
        avg_hr = int(request.form.get("avg_hr", 0) or 0)
        notes = request.form.get("notes", "")
        today_iso = date.today().isoformat()
        cur = conn.execute(
            """INSERT INTO running_log (date, distance_km, duration_min, type, avg_hr, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
            (today_iso, km, duration, run_type, avg_hr, notes),
        )
        rid = cur.lastrowid
        conn.commit()
        conn.close()
        vault_sync.sync_run_async(
            today_iso,
            {"id": rid, "distance_km": km, "duration_min": duration,
             "type": run_type, "avg_hr": avg_hr, "notes": notes},
            _record_vault_result,
        )
        return redirect(url_for("running"))

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM running_log ORDER BY date DESC, id DESC LIMIT 90"
    ).fetchall()]
    week_km, week_target = _marathon_week_km()
    longest = conn.execute(
        "SELECT MAX(distance_km) as m FROM running_log"
    ).fetchone()
    longest_km = float((longest["m"] if longest else 0) or 0)
    conn.close()

    chart = json.dumps([
        {"date": r["date"], "km": r["distance_km"], "type": r["type"]}
        for r in reversed(rows)
    ])

    marathon_phase = _current_phase("marathon")
    return render_template("running.html",
        rows=rows,
        chart=chart,
        week_km=week_km,
        week_target=week_target,
        week_pct=_progress_pct(week_km, week_target),
        longest_km=longest_km,
        longest_pct=_progress_pct(longest_km, 42.2),
        marathon_phase=marathon_phase,
        marathon_phase_label=tasks.PHASE_META[marathon_phase]["label"],
    )


@app.route("/api/progress")
def api_progress():
    """Compact JSON of all progress bars — used by HTMX partials."""
    streak, _ = get_streak()
    sprint_phase = _current_phase("sprint")
    marathon_phase = _current_phase("marathon")
    sprint_done, sprint_total = _phase_progress("sprint", sprint_phase)
    marathon_done, marathon_total = _phase_progress("marathon", marathon_phase)
    week_km, week_target = _marathon_week_km()

    return jsonify({
        "streak": streak,
        "sprint_phase": sprint_phase,
        "marathon_phase": marathon_phase,
        "sprint_progress": {"done": sprint_done, "total": sprint_total},
        "marathon_progress": {"done": marathon_done, "total": marathon_total},
        "marathon_week_km": {"logged": week_km, "target": week_target},
    })


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5757, debug=False)
