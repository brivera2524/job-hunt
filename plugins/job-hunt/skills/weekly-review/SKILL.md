---
name: weekly-review
description: Reviews the past week of the candidate's job search from the Job Search HQ, covering applications sent, response and interview rates by lane, source and fit, stale and ghosted applications, overdue to-dos and referral opportunities, and recommends concrete adjustments. Use when the user asks "how's my job search going", "what's working", "weekly review", "should I change anything", or when the scheduled weekly review starts.
---

# Weekly review

**Where files are.** With the plugin installed, shared files live in `../../shared/` relative to this skill: `shared/references/` (rules.md, hq-schema.md, ats-playbook.md, connectors.md, voice.md, schedules.md), `shared/scripts/` and `shared/templates/`. When this file is being followed as a RUNBOOK from the HQ (a scheduled run without the plugin), the same references are published at the top level of the HQ artifact (`rules.md`, `hq-schema.md`, …) and the scripts as `scripts/<name>.txt`. Fetch them with `Artifact` `action: "read"`, `paths`, `out_dir`, and drop the `.txt` suffix. If a tool named here isn't available (AskUserQuestion, SendUserMessage, SendUserFile, SearchMcpRegistry, SuggestConnectors), do the same thing in plain text in your reply.

Read `shared/references/hq-schema.md` first. This skill reads and reports; the only writes are the run log and, with the user's OK, profile or prefs changes.

## 1. Gather

Find the HQ. List `jobs` (all pages) and the last 14 days of `runs`. Read `settings/profile`, `settings/prefs`, `settings/dossier` (for its referral network) and `settings/answers` (for the voice sample), plus `voice.md`.

## 2. Compute (run the numbers in Python, don't estimate)

- This week and overall: jobs found, applied, responses (Screening, Interviewing, Offer, Rejected), screens or interviews, offers.
- Response rate and screen/interview rate overall, and split by lane, by base resume (`resumeBase`), by fit label, by source (each board or connector), and by apply route.
- Median days from applied to first response, using `history`.
- Ghosted: Applied with no status change for 30 or more days.
- Open to-dos: Needs-you jobs by `needsKind` (accounts: how many accounts and how many jobs behind each; questions; reviews), `actionNeeded` items oldest first, and anything past `actionDue`. Note sign-ins that have waited over 7 days.
- Pipeline health: applications per week against `settings/page.weeklyGoal`.
- Sources: from the last 14 days of "Job search" runs, jobs kept per source (company boards, bulk lists, each aggregator, connectors, alert emails) and any source that returned nothing on several runs in a row. Apply-yourself jobs waiting, and how long the oldest has waited (LinkedIn Easy Apply jobs fill fast).

## 3. Judge, honestly

- Small samples: say so plainly. Under about 30 resolved applications, describe what happened without drawing conclusions. Typical cold-application interview rates run around 3–6% (vendor data), and first interviews often take 3+ weeks.
- **Checkpoint:** three or more weeks in, 30+ applications mostly resolved, and zero screens or interviews means a targeting or positioning problem, not bad luck. Recommend specific changes: narrower lanes, fewer Stretch fits, resume summary and skills wording, referrals.
- When one lane, base resume or source clearly outperforms another, with enough data to say so, recommend shifting effort toward it. A lane whose base resume gets no responses after 15+ resolved applications is a candidate for a revised base: draft the revision and show it. It only replaces the base (version +1) after the user approves.
- Referrals beat cold applications by a wide margin in the best available data. List the top 3 Strong-fit applications or targets where the user has a connection or alumni link, with a draft note for each (voice.md) for them to send.

## 4. Report and log

Write a short report: headline numbers, what changed since last week, two or three recommendations (each with the reason), open to-dos, and referral drafts. Log it as a `runs` document (`kind: "Weekly review"`, the summary plus `items` for recommendations). In a scheduled run, send the report with SendUserMessage. Don't change the profile, filters or prefs without the user's OK: propose the change and apply it when they agree.

Run-log documents follow hq-schema.md "Run document" exactly (`kind`, `at` ISO timestamp, `date`, `time`, `summary`, `items`, `stats`, `problems`); the HQ page orders the log by `at`.
