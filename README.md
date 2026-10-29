# 75hard-tracker — Flask web app for the 75 Hard challenge

![Flask](https://img.shields.io/badge/flask-3.0+-black.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![SQLite](https://img.shields.io/badge/db-sqlite3-lightgrey.svg)
![LLM](https://img.shields.io/badge/llm-ollama%20local-7a5cff.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

A single-user, self-hosted daily tracker built around Andy Frisella's
**75 Hard** challenge, extended with weight trajectory, nutrition logging,
career-sprint tasks, and a marathon training block. One Flask process, one
SQLite file, HTMX in the templates, optional local Ollama for text clean-up
and natural-language log parsing.

---

## 60-second overview

**What is 75 Hard?** A strict 75-day habit challenge. Every day you must:

1. Follow a diet (any diet, zero cheat meals, zero alcohol)
2. Do two 45-minute workouts (one must be outdoors)
3. Drink 1 gallon (~4 L) of water
4. Read 10 pages of a non-fiction / self-development book
5. Take a progress photo
6. (This app also tracks diet + reading as separate booleans so the UI
   mirrors the six rules exactly.)

**The reset rule is what makes 75 Hard "hard":** miss any one task on any
one day — you restart from Day 1. There are no cheat days, no makeups, no
"I'll do it tomorrow". Finish 75 consecutive clean days or start over.

**What this app tracks:**

- The 6 core 75 Hard rules per day → `core_complete` flag + rolling streak
- Weight log on a linear trajectory toward a goal weight by a target date
- Daily metrics: steps, pushups/situps/squats, reading pages, water
- Nutrition log (per-meal calories + protein) with a daily calorie target
- Study hours (weekday 3h / weekend 8h) + LLM-cleaned study notes
- Spending log with a monthly CAD budget bar
- Sprint tasks across 5 phases (career projects) + marathon training
  across 4 phases, each with its own progress bar
- Running log → weekly km, longest run, marathon-race progress toward 42.2 km
- Free-text daily log → parsed asynchronously by a local Ollama model into
  structured fields + auto-ticked tasks
- Optional write-through to a CouchDB "brain" vault for Obsidian sync

---

## For interviewers

### Problem statement

Habit trackers on the App Store either (a) don't enforce 75 Hard's
reset-on-fail rule, so a "streak" keeps counting through missed days, or
(b) silo the challenge away from the rest of life — career project work,
marathon training, weight goal, spending — so the user ends up with four
apps and no single answer to "did I win today?".

This project collapses the whole thing into one Flask app, one SQLite
file, and one HTML dashboard. The streak logic is a single pass over the
`checkins` table in descending date order and breaks the moment it hits a
non-contiguous day — the reset rule is literally a `break` statement.

### Skills demonstrated

- **Flask app design** — single-file app (`app.py`), 20+ routes, HTML form
  posts + a small `/api/*` JSON surface for an external update agent and
  HTMX partials.
- **SQLite data model** — hand-written DDL in `init_db()` with
  idempotent `ALTER TABLE ... ADD COLUMN` migrations (try/except on
  `OperationalError`), upserts via `ON CONFLICT DO UPDATE`, named-param
  binding (`:field`) to avoid positional drift.
- **Jinja templates + HTMX** — server-rendered pages with HTMX partials
  for in-place task-tick UX; `_log_result.html` returned as HTML fragment
  when the request carries `HX-Request`.
- **Form validation & coercion** — defensive `int(f.get("x") or 0)` and
  `float(... or 0)` throughout the check-in POST so blank inputs don't
  500, with an `is_core_complete()` predicate that computes
  `core_complete` once per write.
- **Streak logic + reset rule** — the entire rule is 15 lines in
  `get_streak()`: ORDER BY date DESC, walk backward, `break` on any gap.
  The reset-on-fail is a side effect of only counting rows where
  `core_complete=1`.
- **Date / phase handling** — `date.today()` + `timedelta` throughout;
  explicit phase windows (`PHASE_WINDOWS`, `MARATHON_WINDOWS`) with a
  "today's phase" lookup that falls back to the next upcoming window
  when none is active.
- **Linear trajectory projection** — `marriage_stats()` computes
  "today's ideal weight" on a 135→100 kg linear line between the start
  date and the target date, plus the daily kg-loss rate needed and the
  implied daily calorie deficit.
- **Background work & async LLM** — raw daily logs are written to SQLite
  synchronously and parsed by a daemon `threading.Thread` so the UI
  never blocks on Ollama; failures mark the row `status='failed'`
  without crashing the request.
- **Local LLM integration** — `llm_format()` (free-text) and
  `llm_json()` (structured, `format=json`) both wrap Ollama's
  `/api/generate` with short timeouts and a graceful fallback to the raw
  input, plus a `_normalize_parsed()` layer that maps the model's
  invented field names back to the schema and coerces string numbers.
- **External write-through** — `vault_sync.py` posts daily snapshots and
  run logs to a CouchDB endpoint over Tailscale, fire-and-forget, with
  every attempt logged to `vault_sync_log` for later debugging.
- **Pragmatic layering** — Jinja for pages, HTMX for interactive bits,
  JSON APIs for machine clients; no SPA, no build step, no bundler.

### Architecture

```
                   ┌───────────────────────────┐
   browser ──────► │  Flask app (app.py)       │ ──► Jinja templates (templates/*.html)
   (HTMX)          │   • 20+ routes            │
                   │   • streak + phase logic  │
                   │   • form coercion         │
                   └──────┬────────────┬───────┘
                          │            │
             sqlite3 ◄────┘            └────► Ollama (localhost:11434)
             tracker.db                       /api/generate (sync+async)
             ├─ checkins                       - study_notes clean-up
             ├─ weight_log                     - spending_notes clean-up
             ├─ nutrition_log                  - daily_log JSON parse
             ├─ projects
             ├─ sprint_tasks
             ├─ running_log
             ├─ daily_log
             ├─ daily_targets
             └─ vault_sync_log
                          │
                          └────► vault_sync.py ──► CouchDB (brain LXC, Tailscale)
                                 (fire-and-forget, logged)
```

### Design decisions

- **Why Flask, not FastAPI?** 95% of the surface is server-rendered HTML
  with HTMX. FastAPI is optimised for JSON APIs and async; Flask gives a
  smaller mental model for templates + forms, and `threading.Thread` is
  all the async this app needs.
- **Why SQLite, not Postgres?** Single-user, single-host, hundreds of
  rows per table at most. The file *is* the backup. Postgres would add a
  daemon and a connection pool for zero functional gain.
- **Why hand-written SQL instead of SQLAlchemy?** The schema is small
  and the queries are mostly single-table. Named-param binding
  (`:field`) + `sqlite3.Row` gives dict-like rows with none of the ORM
  layer. Idempotent `ALTER TABLE ... ADD COLUMN` wrapped in
  `try/except OperationalError` handles migrations without an extra
  dependency.
- **How is reset-on-fail detected?** It isn't, explicitly. `get_streak()`
  walks `checkins WHERE core_complete=1 ORDER BY date DESC`. The moment
  it meets a date that isn't `yesterday - streak`, the loop breaks. If
  you miss a day, that day is either absent from the table or present
  with `core_complete=0` — either way, the walk stops and the streak is
  whatever you had before the miss. Starting again just means the next
  streak begins fresh on the next clean day.
- **Why thread, not Celery / RQ?** Daily log parse is the only async
  job. One thread per request, daemon=True, failures logged into a
  table. If this ever scales beyond one user, swap in RQ — the parse
  function is already a pure `(log_id, text, today_iso)` call.
- **Why a local LLM?** All data is personal (weight, spending,
  habits). Ollama runs on `localhost:11434` and the prompts stay on
  the box. Falls back to the raw string if Ollama is down — the app
  works without it.

### Metrics

- `app.py`: ~1,400 lines, 20+ routes, 1 Flask app
- `tasks.py`: sprint + marathon task catalog (source of truth; re-seeded on boot)
- `vault_sync.py`: CouchDB write-through (~fire-and-forget)
- Templates: 10 (`dashboard`, `checkin`, `weight`, `nutrition`,
  `history`, `projects`, `sprint`, `running`, `base`, `_log_result`)
- SQLite tables: 9 (`checkins`, `weight_log`, `nutrition_log`,
  `projects`, `sprint_tasks`, `running_log`, `daily_log`,
  `daily_targets`, `vault_sync_log`)
- External deps: `flask>=3.0`, `requests>=2.31`. That's it.

---

## Quick start

```bash
# clone
cd ~/projects
git clone <your-fork-url> 75hard-tracker
cd 75hard-tracker

# venv + deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# run (binds 0.0.0.0:5757, auto-creates tracker.db on first boot)
python app.py
```

Open `http://localhost:5757` — the dashboard loads with an empty streak,
start-weight placeholder, and the sprint/marathon phase for today.
Fill out `/checkin` to log day 1, hit `/weight` to log your first weigh-in.

> **Note:** There is no login / "create account" flow — this is a
> single-user, LAN-local tool. If you expose it beyond localhost, put a
> reverse proxy (Caddy, nginx) with basic auth in front of it.

---

## Daily flow

A real day with the app:

1. **Morning weigh-in** → `POST /weight` with today's kg. The dashboard
   chart updates immediately; the trajectory line shows whether you're
   ahead or behind the linear target between start-weight and
   goal-weight.
2. **During the day** → log meals via `/nutrition` as you eat (meal
   name, description, calories, protein_g). The calorie bar on the
   dashboard adds them up.
3. **Evening check-in** → `/checkin`. Tick the 6 core 75 Hard boxes
   (diet, workout 1, workout 2 outdoor, water 4L, reading, progress
   photo), fill in metrics (steps, pushups, situps, squats, reading
   pages, study hours, spending), paste raw study notes and raw
   spending text — the LLM cleans them before save.
4. **Submit** → `core_complete` is computed from the 6 booleans, the
   row is upserted, the vault sync fires in the background. If all 6
   are green, your streak extends.
5. **Lazy mode** → instead of the full check-in form, type one free
   sentence into the daily log widget on the dashboard
   (`POST /sprint/log`), e.g. *"Ran 6k outdoor, lifted 45 min, 4L water,
   10 pages, on plan, progress photo."* A background thread hits the
   local LLM, extracts fields, keyword-matches sprint tasks, and ticks
   the right boxes. UI shows "Queued — refresh in ~30s".

---

## Features

- Six 75 Hard rules enforced as a single `core_complete` predicate; miss
  one → streak resets implicitly on the next walk.
- Rolling streak with a 14-day visual bar (green = complete, grey = miss).
- Weight log with target-trajectory overlay toward a goal weight by a
  target date; "behind by X kg" / "ahead by X kg" callout.
- Nutrition log — per-meal calories/protein, daily total vs. target.
- Sprint board — 5 phases of career-project tasks (`phase0`..`phase4`),
  per-phase progress bars, click-to-tick (HTMX partials).
- Marathon training — 4 training blocks (`marathon_a`..`marathon_d`)
  with phase-specific weekly km targets; running log with longest-run
  tracker (progress toward 42.2 km).
- Free-text daily log → local LLM extracts running, weight, reading
  pages, pushups, situps, squats, steps, study_hours, water_L into
  structured fields; keyword-matches sprint-task descriptions for
  auto-ticking.
- Study notes + spending-log LLM-cleanup synchronously on the
  check-in POST (short timeout, falls back to raw on any failure).
- `/api/state` and `/api/progress` JSON endpoints for external agents
  (e.g. a Telegram bot or a dashboard tile).
- Optional CouchDB write-through to an Obsidian LiveSync vault — every
  check-in and run is mirrored into a daily note for permanent record.

---

## Examples

### 1. A normal day — all six boxes checked

```
POST /checkin
  diet_followed=on
  workout1_done=on   workout1_type=Lift
  workout2_done=on   workout2_outdoor=on
  water_4l=on
  reading_done=on    reading_pages=12
  progress_photo=on
  steps=11250  pushups=50  situps=50  squats=100
  study_hours=3.5
  study_notes_raw="read chapter 4 of designing data intensive apps, learned about..."
  spending_raw="coffee $5, groceries $84 at save on, gas $45"
```

Result: `core_complete=1` → streak = N+1. Study notes come back as a
clean 2-4 line summary; spending comes back as a bullet list with a
Total line.

### 2. A miss — the reset rule in action

Previous streak = 11 days. Today, water came up short:

```
POST /checkin
  diet_followed=on
  workout1_done=on
  workout2_done=on   workout2_outdoor=on
  water_4l=       <-- unchecked (drank 3L)
  reading_done=on
  progress_photo=on
```

`is_core_complete()` → `False` → `core_complete=0` is written to the row.
Tomorrow's `get_streak()` walks back from today, sees today's row has
`core_complete=0` (not `1`), and the loop stops. Streak = 0. Day 1
restarts whenever you have your next clean day.

### 3. Lazy evening log via the LLM

Dashboard widget → one sentence:

```
POST /sprint/log
  text=Ran 6k outdoor easy pace, 32 min, 148 avg hr. 4L water, 12 pages
       of Deep Work, lifted 45 min at the gym, stayed on plan, took the
       photo.
```

Background thread (~5-30s depending on model):

- `_parse_and_apply()` → Ollama returns
  `{"running": {"km": 6, "duration_min": 32, "avg_hr": 148, "type": "easy"}, "reading_pages": 12, "water_L": 4, "summary": "..."}`
- `_normalize_parsed()` canonicalises keys + applies the m→km heuristic
  if the model returns `6000`.
- Keyword matcher checks for "diet"/"on plan"/"progress photo"/"outdoor"
  and marks `diet_followed`, `progress_photo`, `workout1_done`,
  `workout2_done`, `workout2_outdoor` streaks.
- `water_L >= 4` → `water_4l=1`. `reading_pages >= 5` → `reading_done=1`.
- Row updated, `core_complete` recomputed, running row inserted,
  `daily_log.status='parsed'`. Vault sync fires.

Refresh dashboard → streak extended, run shows up in `/running`,
sprint tasks matching the text are auto-ticked.

---

## Technical reference

### Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt`:

```
flask>=3.0
requests>=2.31
```

### Config (environment variables)

| Variable           | Default                              | Purpose                                                   |
|--------------------|--------------------------------------|-----------------------------------------------------------|
| `OLLAMA_URL`       | `http://localhost:11434`             | Ollama endpoint for text clean-up + log parsing.          |
| `OLLAMA_MODEL`     | `llama3.2:3b`                        | Model used for free-text clean-up (study / spending).    |
| `OLLAMA_JSON_MODEL`| `llama3.2:3b`                        | Model used for structured JSON extraction (daily log).   |
| `BRAIN_URL`        | `https://brain.taila06bcc.ts.net`    | CouchDB endpoint for vault write-through.                |
| `BRAIN_DB`         | `obsidian_brain`                     | CouchDB database name.                                   |
| `BRAIN_USER`       | `brain-admin`                        | CouchDB user.                                            |
| `BRAIN_PASS`       | *(empty)*                            | CouchDB password — leave empty to disable vault sync.    |
| `BRAIN_RESOLVE_IP` | *(empty)*                            | Optional Host-header pin for Tailscale cert validation.  |
| `BRAIN_VERIFY_TLS` | `false`                              | Set `true` once your CA trust is sorted.                 |

Hard-coded constants at the top of `app.py` you may want to tweak:
`START_WEIGHT`, `GOAL_WEIGHT`, `MARRIAGE_DATE` (target date),
`WEIGHT_START_DATE`, `CALORIE_TARGET`, `BUDGET_MONTHLY_CAD`,
`SPRINT_START`, `SPRINT_END`.

### Routes

| Method    | Path                               | Purpose                                                            |
|-----------|------------------------------------|--------------------------------------------------------------------|
| GET       | `/`                                | Dashboard: streak, weight bar, metric bars, sprint/marathon today. |
| GET/POST  | `/checkin`                         | Full daily check-in form; computes `core_complete` on POST.        |
| GET/POST  | `/weight`                          | Weight log + trajectory chart.                                     |
| GET/POST  | `/nutrition`                       | Per-meal nutrition log.                                            |
| POST      | `/nutrition/delete/<meal_id>`      | Delete a logged meal.                                              |
| GET       | `/history`                         | Last 75 check-ins, raw.                                            |
| GET/POST  | `/projects`                        | Career projects status/commits/last-commit.                        |
| GET       | `/sprint`                          | Sprint + marathon board with per-phase groups.                     |
| POST      | `/sprint/tick/<task_key>`          | Toggle a sprint/marathon task; HTMX-aware response.                |
| POST      | `/sprint/log`                      | Free-text daily log; parses async via Ollama.                      |
| GET/POST  | `/running`                         | Running log + weekly km + longest-run.                             |
| POST      | `/api/format`                      | AJAX LLM clean-up for raw study/spending text.                     |
| GET       | `/api/state`                       | Machine-readable snapshot (for update agents).                     |
| GET       | `/api/progress`                    | Compact JSON of streak + phase bars (HTMX partials).               |

### DB schema (abridged)

```sql
checkins        (id, date UNIQUE, diet_followed, workout1_done,
                 workout2_done, workout2_outdoor, water_4l, reading_done,
                 reading_pages, progress_photo, steps, pushups, situps,
                 squats, study_hours, study_notes_raw, study_notes,
                 money_spent, spending_raw, spending_notes, spending_total,
                 calories_today, morning_cardio_type, morning_cardio_minutes,
                 evening_weights_done, evening_weights_notes,
                 paath_done, kegels_done, skincare_done, haircare_done,
                 core_complete, created_at, updated_at)

weight_log      (id, date, weight_kg, notes, created_at)
nutrition_log   (id, date, meal, description, calories, protein_g, created_at)
projects        (id, code UNIQUE, name, timeline, status, commits_week,
                 last_commit, updated_at)
sprint_tasks    (id, track, phase, task_key UNIQUE, description,
                 due_week, done, done_date, note)
running_log     (id, date, distance_km, duration_min, type, avg_hr,
                 notes, created_at)
daily_log       (id, date, raw_text, parsed_json, status, created_at, parsed_at)
daily_targets   (id, key UNIQUE, weekday_target, weekend_target, unit, label)
vault_sync_log  (id, doc_id, rev, synced_at, status)
```

### Deploy — systemd unit

```ini
# /etc/systemd/system/75hard.service
[Unit]
Description=75hard-tracker
After=network.target

[Service]
Type=simple
User=tony
WorkingDirectory=/home/tony/projects/75hard-tracker
Environment=OLLAMA_URL=http://localhost:11434
Environment=OLLAMA_MODEL=llama3.2:3b
ExecStart=/home/tony/projects/75hard-tracker/venv/bin/python app.py
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now 75hard
```

### Deploy — Docker (optional)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5757
CMD ["python", "app.py"]
```

```bash
docker build -t 75hard .
docker run -d --name 75hard -p 5757:5757 -v $(pwd)/tracker.db:/app/tracker.db 75hard
```

### Extending

- **New metric?** Add a column via `ALTER TABLE checkins ADD COLUMN
  <name> <type> DEFAULT <default>` block in `init_db()` — the
  try/except pattern makes it a no-op on existing installs. Add the
  field to the `data` dict in the `/checkin` POST and the Jinja form.
- **New sprint/marathon task?** Append to `tasks.TASKS` in `tasks.py`
  — the upsert in `init_db()` seeds it with a stable `task_key` so
  existing ticks survive.
- **New API consumer?** Return more fields from `/api/state` or add
  a route — the pattern is `conn.execute(...).fetchone/all()`,
  `dict(row)`, `jsonify(...)`.

---

## Why this was built

Two reasons that landed on the same codebase:

1. **I'm doing 75 Hard and nothing on the App Store enforces the reset
   rule honestly.** The streak in most trackers keeps running through
   gaps if you fill in yesterday retroactively; 75 Hard rules say the
   day fails the moment the clock rolls past midnight with any task
   unchecked. One `core_complete=1` boolean + an `ORDER BY date DESC`
   walk is the correct implementation and nothing shipped did it.
2. **Flask skills refresh.** Day-job work drifted toward FastAPI +
   async; wanted a small, honest server-rendered app with forms, Jinja,
   HTMX partials, SQLite, and a background thread to parse free-text
   logs via a local LLM. 75 Hard is a convenient excuse for a project
   with a hard, specific rule set.

---

## FAQ

**Q: Does the app enforce "restart from Day 1" automatically?**
No, and it doesn't need to. `get_streak()` walks the `checkins` table
backward from today, counting only consecutive days where
`core_complete=1`. Miss a day → the walk stops at that gap → the streak
drops to whatever existed before the miss. Starting again just means
the next streak begins fresh on your next clean day. The reset *is* the
loop breaking.

**Q: What if I log a day late — does backfill cheat the streak?**
Backfilling fills the gap in the table, so if the backfilled day's
`core_complete` is 1 the streak heals. That is deliberate — this is a
personal tool, not an exam. If you want to make backfill impossible,
reject POSTs where `date != today` in `/checkin`.

**Q: Do I need Ollama running?**
No. If Ollama is unreachable, `llm_format()` falls back to the raw
input and the check-in still saves. The free-text `/sprint/log` endpoint
will mark the row `status='failed'` after a timeout but your streak,
weight, and tasks are unaffected.

**Q: Where are progress photos stored?**
Nowhere — the `progress_photo` field is a boolean ("did you take one?"),
not an upload. Photos live on your phone's camera roll by design;
storing them in SQLite would bloat the file and complicate backup.

**Q: Can two people use the same instance?**
Not safely. There is no user table, no auth, no per-user partitioning.
This is a single-user tool. Run two instances on two ports with two DB
files if you want to share hardware.

**Q: How do I back up?**
Copy `tracker.db`. That's it. SQLite is a single file; `cp tracker.db
tracker.db.$(date +%F).bak` is a complete backup. If vault sync is
enabled, you also have a mirrored write-through to CouchDB.

---

## License

MIT. See `LICENSE` if present, otherwise assume MIT.
