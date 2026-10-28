"""Sprint + marathon task source of truth.

Mirrors ``10-projects/senior-sprint-2027.md`` in the brain vault. Edit here and
redeploy to update the DB seed on next boot. Task keys are stable so ticks
survive edits.
"""
from __future__ import annotations

from typing import TypedDict


class Task(TypedDict, total=False):
    track: str        # 'sprint' | 'marathon' | 'extra'
    phase: str        # 'phase0'..'phase4' | 'marathon_a'..'marathon_d' | 'prep'
    task_key: str     # stable id
    description: str
    due_week: int | None


TASKS: list[Task] = [
    # ── Phase 0 — sprint buffer (Oct 27 → Dec 31 2026) ───────────────────────
    {"track": "sprint", "phase": "phase0", "task_key": "p0_teammate_intel",
     "description": "Teammate intel: role, company, recruiter, loop, comp. Request referral for sprint start."},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_p1_readme",
     "description": "P1 README polish: 'AI-triaged SAST/DAST, 40% FP reduction'"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_p2_readme",
     "description": "P2 README polish: 'LLM-generated STRIDE threat models'"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_p3_readme",
     "description": "P3 README polish: 'LLM-driven log anomaly w/ MITRE mapping'"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_p4_readme",
     "description": "P4 README polish: 'AI pentest report writer'"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_p5_readme",
     "description": "P5 ATLAS README polish: 'Autonomous HTB — 6 agents, tiered caching, SSH priv-esc'"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_p6_readme",
     "description": "P6 Council README polish: '5-persona AI briefing, voice + text'"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_linkedin",
     "description": "LinkedIn rebuild: headline AI-augmented security, pin P5+AI Hacking Team"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_resume_v1",
     "description": "Resume v1: STAR bullets w/ numbers, lead w/ '6 shipped AI-security tools'"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_htb_weekly",
     "description": "HTB machine weekly — writeup to GitHub + blog + LinkedIn"},
    {"track": "sprint", "phase": "phase0", "task_key": "p0_blog_biweekly",
     "description": "Blog post every 2 wks: 'How I use Claude for X' series"},

    # ── Phase 1 — Jan 1-28 2027 — signal ─────────────────────────────────────
    {"track": "sprint", "phase": "phase1", "task_key": "p1_htb_wk",
     "description": "HTB machine / wk + writeup", "due_week": 4},
    {"track": "sprint", "phase": "phase1", "task_key": "p1_blog_wk",
     "description": "1 blog post / wk — 'How I use Claude to X'", "due_week": 4},
    {"track": "sprint", "phase": "phase1", "task_key": "p1_apply_10",
     "description": "Apply 10 roles / wk (LinkedIn, Wellfound, Dice, Otta)", "due_week": 4},
    {"track": "sprint", "phase": "phase1", "task_key": "p1_cold_dm_10",
     "description": "Cold DM 10 security engineers / wk w/ specific comment", "due_week": 4},
    {"track": "sprint", "phase": "phase1", "task_key": "p1_referral_request",
     "description": "Day 1: request teammate referral"},

    # ── Phase 2 — Jan 29 → Mar 11 — proof of work ────────────────────────────
    {"track": "sprint", "phase": "phase2", "task_key": "p2_htb_wk",
     "description": "HTB / wk continues", "due_week": 10},
    {"track": "sprint", "phase": "phase2", "task_key": "p2_loom_demos",
     "description": "60-sec Loom demo per project P1-P6, post weekly", "due_week": 10},
    {"track": "sprint", "phase": "phase2", "task_key": "p2_oss_tool",
     "description": "Open-source 1 new tool: ai-sigma-gen (detection rules from writeups)"},
    {"track": "sprint", "phase": "phase2", "task_key": "p2_mock_interview_2wk",
     "description": "Mock interviews 2 / wk: Pramp + interviewing.io", "due_week": 10},
    {"track": "sprint", "phase": "phase2", "task_key": "p2_apply_15",
     "description": "Apply 15 / wk", "due_week": 10},

    # ── Phase 3 — Mar 12 → May 6 — scale signal ──────────────────────────────
    {"track": "sprint", "phase": "phase3", "task_key": "p3_prolabs",
     "description": "HTB → Pro Labs (Dante, Offshore)"},
    {"track": "sprint", "phase": "phase3", "task_key": "p3_bsides_talk",
     "description": "Speak: BSides Vancouver, DefCon group — 'Autonomous HTB w/ Claude agents'"},
    {"track": "sprint", "phase": "phase3", "task_key": "p3_x_thread_wk",
     "description": "Twitter/X + Mastodon: 1 technical thread / wk", "due_week": 18},
    {"track": "sprint", "phase": "phase3", "task_key": "p3_inbound_recruiter",
     "description": "Target: 1 inbound recruiter / wk by week 15", "due_week": 15},

    # ── Phase 4 — May 7 → Jun 27 — close ─────────────────────────────────────
    {"track": "sprint", "phase": "phase4", "task_key": "p4_3_offers",
     "description": "3+ offers in flight simultaneously"},
    {"track": "sprint", "phase": "phase4", "task_key": "p4_negotiate",
     "description": "Negotiate using competing offers"},
    {"track": "sprint", "phase": "phase4", "task_key": "p4_hard_target",
     "description": "Hard target: $200k USD remote (~$275k CAD)"},
    {"track": "sprint", "phase": "phase4", "task_key": "p4_floor",
     "description": "Floor: $160k CAD remote Canadian co"},
    {"track": "sprint", "phase": "phase4", "task_key": "p4_walk_sub_floor",
     "description": "Walk if sub-floor"},

    # ── Extra sprint prep ────────────────────────────────────────────────────
    {"track": "extra", "phase": "prep", "task_key": "x_github_profile",
     "description": "GitHub profile README: pinned repos, AI security tagline, metrics widgets"},
    {"track": "extra", "phase": "prep", "task_key": "x_personal_website",
     "description": "Personal website shipped: portfolio + live CVE feed + blog"},
    {"track": "extra", "phase": "prep", "task_key": "x_levels_fyi",
     "description": "levels.fyi + Blind research — comp benchmarks for target companies"},
    {"track": "extra", "phase": "prep", "task_key": "x_remote_structure",
     "description": "US remote employment structure decided (contractor / EOR / subsidiary)"},
    {"track": "extra", "phase": "prep", "task_key": "x_oss_prs",
     "description": "OSS PRs: Semgrep, Trivy, Nuclei, OSV-Scanner, Wazuh rules, Sigma, Atomic Red Team"},
    {"track": "extra", "phase": "prep", "task_key": "x_sysdesign_prep",
     "description": "System design prep — Design SIEM / detection pipeline / AI red team platform"},
    {"track": "extra", "phase": "prep", "task_key": "x_anki_deck",
     "description": "Security interview Anki deck: AD, cloud IAM, OWASP, SIEM, LLM security"},
    {"track": "extra", "phase": "prep", "task_key": "x_ctf_team",
     "description": "Join competing CTF team (DEFCON quals / HTB Business CTF)"},
    {"track": "extra", "phase": "prep", "task_key": "x_cfp_submit",
     "description": "Conference CFPs: BSides Vancouver 2027, BSidesSF, DEFCON AI Village"},
    {"track": "extra", "phase": "prep", "task_key": "x_linkedin_recs",
     "description": "LinkedIn recs: 3 colleagues + manager — ask in Dec"},
    {"track": "extra", "phase": "prep", "task_key": "x_references",
     "description": "Reference list: 3 strong vouchers, warn May"},
    {"track": "extra", "phase": "prep", "task_key": "x_tax_consult",
     "description": "Canadian-US cross-border tax specialist consult (~$500)"},

    # ── Marathon Phase A — Base (Nov 2026 → Jan 2027) ────────────────────────
    {"track": "marathon", "phase": "marathon_a", "task_key": "ma_gait_shoes",
     "description": "Gait analysis + proper shoes (Running Room / Forerunners Vancouver)"},
    {"track": "marathon", "phase": "marathon_a", "task_key": "ma_3_runs_wk",
     "description": "3 easy runs/wk, Z2 only (<150 bpm)"},
    {"track": "marathon", "phase": "marathon_a", "task_key": "ma_build_45min",
     "description": "Build 15 min → 45 min easy"},
    {"track": "marathon", "phase": "marathon_a", "task_key": "ma_strength_2x",
     "description": "Strength 2x/wk — compound lifts, posterior chain, calves"},
    {"track": "marathon", "phase": "marathon_a", "task_key": "ma_mobility_daily",
     "description": "Mobility daily — hips, ankles"},

    # ── Marathon Phase B — Build (Jan → Mar 2027) ────────────────────────────
    {"track": "marathon", "phase": "marathon_b", "task_key": "mb_4_runs_wk",
     "description": "4 runs/wk: 1 long slow, 2 easy, 1 tempo"},
    {"track": "marathon", "phase": "marathon_b", "task_key": "mb_long_20k",
     "description": "Long run: 10km → 20km progression (10% weekly cap)"},
    {"track": "marathon", "phase": "marathon_b", "task_key": "mb_10k_race",
     "description": "First 10k race in Feb (BMO 8k / YMCA Lunar Dash)"},
    {"track": "marathon", "phase": "marathon_b", "task_key": "mb_strength_2x",
     "description": "Strength 2x/wk continues"},

    # ── Marathon Phase C — Peak (Mar → mid-Apr 2027) ─────────────────────────
    {"track": "marathon", "phase": "marathon_c", "task_key": "mc_5_runs_wk",
     "description": "5 runs/wk, peak 55-65 km total"},
    {"track": "marathon", "phase": "marathon_c", "task_key": "mc_long_35k",
     "description": "Long run: 25km → 32km → 35km"},
    {"track": "marathon", "phase": "marathon_c", "task_key": "mc_half_marathon",
     "description": "Half marathon race wk 6 (First Half Vancouver)"},
    {"track": "marathon", "phase": "marathon_c", "task_key": "mc_mp_workouts",
     "description": "Marathon-pace workouts: 2x5km @ goal pace"},

    # ── Marathon Phase D — Taper + race (mid-Apr → May 2) ────────────────────
    {"track": "marathon", "phase": "marathon_d", "task_key": "md_taper",
     "description": "2 wk taper, 50% volume"},
    {"track": "marathon", "phase": "marathon_d", "task_key": "md_race_bmo",
     "description": "Race BMO Vancouver Marathon 2027-05-02"},
    {"track": "marathon", "phase": "marathon_d", "task_key": "md_recovery",
     "description": "Post-race recovery → maintain through Jun 27"},
]


PHASE_META: dict[str, dict] = {
    "phase0":     {"label": "Phase 0 — Buffer (Oct 27 → Dec 31 2026)",         "track": "sprint",   "order": 0},
    "phase1":     {"label": "Phase 1 — Signal (Jan 1-28 2027)",                "track": "sprint",   "order": 1},
    "phase2":     {"label": "Phase 2 — Proof of Work (Jan 29 → Mar 11 2027)",  "track": "sprint",   "order": 2},
    "phase3":     {"label": "Phase 3 — Scale Signal (Mar 12 → May 6 2027)",    "track": "sprint",   "order": 3},
    "phase4":     {"label": "Phase 4 — Close (May 7 → Jun 27 2027)",           "track": "sprint",   "order": 4},
    "prep":       {"label": "Extra sprint prep (anytime)",                      "track": "extra",    "order": 5},
    "marathon_a": {"label": "Marathon A — Base (Nov 2026 → Jan 2027)",         "track": "marathon", "order": 10},
    "marathon_b": {"label": "Marathon B — Build (Jan → Mar 2027)",             "track": "marathon", "order": 11},
    "marathon_c": {"label": "Marathon C — Peak (Mar → mid-Apr 2027)",          "track": "marathon", "order": 12},
    "marathon_d": {"label": "Marathon D — Taper + Race (mid-Apr → May 2 2027)", "track": "marathon", "order": 13},
}


DAILY_TARGETS = [
    # (key, weekday_target, weekend_target, unit, label)
    ("water_L",        4.0,   4.0, "L",     "Water"),
    ("steps",          10000, 15000, "steps", "Steps"),
    ("reading_pages",  10,    10,  "pages", "Reading"),
    ("pushups",        50,    100, "reps",  "Pushups"),
    ("situps",         50,    100, "reps",  "Situps"),
    ("squats",         50,    100, "reps",  "Squats"),
    ("study_hours",    3,     8,   "hours", "Study"),
    ("spending_daily", 50,    50,  "CAD",   "Spending cap"),
]


MARATHON_WEEKLY_KM = {
    # phase → target km/wk
    "marathon_a": 20,
    "marathon_b": 40,
    "marathon_c": 60,
    "marathon_d": 30,
}
