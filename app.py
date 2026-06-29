#!/usr/bin/env python3
"""75 Hard daily tracker — Flask app for GP Singh."""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "tracker.db"
OLLAMA_URL = "http://100.126.22.55:11434"
OLLAMA_MODEL = "llama3.1:70b"
START_WEIGHT = 135.0
GOAL_WEIGHT = 100.0
MARRIAGE_DATE = date(2026, 10, 16)   # 110 days from 2026-06-28
WEIGHT_START_DATE = date(2026, 6, 28)
CALORIE_TARGET = 1500


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
        data.get("progress_photo"),
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
            timeout=45,
        )
        if resp.ok:
            return resp.json().get("response", raw).strip()
    except Exception:
        pass
    return raw


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
        "SELECT date, weight_kg FROM weight_log ORDER BY date DESC LIMIT 1"
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
    weight_rows = conn.execute(
        "SELECT date, weight_kg FROM weight_log ORDER BY date ASC LIMIT 90"
    ).fetchall()

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

    return render_template("dashboard.html",
        today=today,
        today_row=today_row,
        streak=streak,
        streak_start=streak_start,
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
        "SELECT date, weight_kg, notes FROM weight_log ORDER BY date DESC LIMIT 90"
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
        "SELECT weight_kg FROM weight_log ORDER BY date DESC LIMIT 1"
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


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5757, debug=False)
