# Job Search HQ: data model

The HQ is one private artifact (a published page with the `db` capability) that holds everything the plugin needs between sessions. Its page shows run status, a "Needs you" queue split by kind (sign-ins grouped by account, questions, reviews, other blocks, to-dos), an "Apply next" queue, the job tracker and an activity log. Buttons on the page write to the database; the next run reads what they wrote (see "What the page writes" below). Its database holds the user's data and the plugin's state. Read and write it with the `ArtifactData` tool, always passing the HQ `url`.

## Finding the HQ

1. If the prompt or conversation gives an HQ URL, use it.
2. Otherwise call `Artifact` with `action: "list"` and look for a title starting with "Job Search HQ". If there are several, ask which one.
3. If none exists, the user hasn't run setup: offer to run the `setup` skill.

## Collections and documents

| Path | Purpose |
|---|---|
| `jobs/<id>` | One document per job (schema below). Ids are `j` plus a number; new ids continue from the highest existing number (compare numerically, keep the zero-padding style already in use). Imported trackers keep their old ids. |
| `runs/<id>` | One document per run. Id: `<YYYYMMDD-HHMM>-<kind>`. |
| `settings/page` | What the page shows: `{title, lanes: {"1": "Support", ...,"0": "Other"}, regions: {"local": "Austin", "remote": "Remote"}, weeklyGoal, schedule}`. `schedule` is a list of `{kind, when, note, maxGapDays}` (one per scheduled task, `kind` matching the run kinds, `when` in plain words like "daily 6:45am and 5:45pm", `note` such as "needs your computer on with Chrome open", `maxGapDays` after which the page warns that the task hasn't run). Also `scheduleSince` (YYYY-MM-DD the tasks were created), so the page can warn about a task that has never logged a run. Setup and any schedule change keep both current. |
| `accounts/<key>` | One document per job-site account the user has made or declined: `{key, name, system, status: "ready" \| "expired" \| "skipped", readyOn, skippedOn, url}`. `key` comes from `jobfeed.py account <url>` (for example `workday:axos`, `apple`, `icims:careers-peraton`; `smartrecruiters` is one account across companies). A held job with no account rule groups by its site (`site:<host>`) on the page. The page writes "ready" and "skipped"; apply writes "expired" when it meets a sign-in screen on an account marked ready. |
| `settings/prefs` | `{approvalMode: "review"|"auto", dailyCap: 8, perEmployerCap: 2, allowStretch: true, acceptPrivacyAck: true, timezone: "America/Los_Angeles"}` |
| `settings/profile` | `{markdown}`: the search profile (targets, lanes, locations, dealbreakers, fit labels). Filled from templates/profile_template.md. |
| `settings/dossier` | `{markdown}`: the ground-truth dossier. Filled from templates/dossier_template.md. |
| `settings/answers` | `{markdown}`: approved answers to common application questions, in the user's voice. |
| `settings/resume_bank` | The resume bullet bank JSON (format in scripts/build_resume.py). |
| `settings/base_resumes` | One approved base resume spec per lane: `{"<lane id>": {version, approvedOn, file, summary, skills, experience, projects}}`. Tailoring for a job starts from its lane's base. Changing a base needs the user's approval and bumps `version`. |
| `settings/config` | The feed config JSON: `{filters, workday_search_terms, watchlist}` (format in templates/config_template.json). |
| `state/seen` | `{entries: ["<job key>|<YYYY-MM-DD>", ...], updated}`: postings the feed already showed. Prune entries older than 120 days when writing. |
| `state/email` | `{lastCheck: ISO time, processed: ["<gmail message id>", ...]}`: keep the newest 2,000 ids. A missing document means a 14-day lookback. |
| `state/apply` | `{date: YYYY-MM-DD, count}`: applications submitted today, for the daily cap. Treat a missing document as count 0 and create it. |

Large documents (dossier, resume bank, config, seen) are easiest to write with `file_path` pointing at a local JSON file whose top-level object is the document.

Every write to an existing document needs `if_version` from your most recent read. Use `batch` for more than two writes (max 50 per batch).

## Published files on the HQ artifact

Setup publishes the plugin scripts next to the page so scheduled sessions can run them even when the plugin itself isn't loaded:

- `scripts/jobfeed.py.txt`, `scripts/build_resume.py.txt`, `scripts/form_helpers.js.txt`

Fetch them with `Artifact` `action: "read"`, `paths: [...]`, `out_dir`, then drop the `.txt` suffix. Prefer the plugin's own copies (`shared/scripts/` in the plugin) when they're available, since they may be newer.

## Job document

```
{
  company, title, url,                     // url = the employer's own posting whenever possible
  location,                                // human-readable, e.g. "Austin, TX (hybrid)" or "Remote US"
  region,                                  // a key of settings/page.regions, e.g. "local" or "remote"
  pay, years,                              // as posted ("Not listed" / "Not stated" when absent)
  lane,                                    // a key of settings/page.lanes (number)
  fit, fitRank,                            // "Strong" 0 | "Possible" 1 | "Stretch" 2
  note,                                    // one plain sentence: why it fits and the main gap
  top,                                     // true = "Apply first"
  status,                                  // required; exactly one of the eight statuses below (the page
                                           // loads jobs by status, so a missing or misspelled status hides the job)
  statusUpdatedOn, appliedOn, foundOn,     // YYYY-MM-DD
  source,                                  // where it was found: "greenhouse", "indeed", "imported", "you", ...
  applyRoute,                              // "no_account" (Claude can submit) | "needs_account" (user signs in first)
                                           // | "check" (job-board link: find the employer posting, then re-route)
                                           // Always derive it from the URL with jobfeed.py's rules, never copy it from an import.
  account,                                 // needs_account jobs: the account key (jobfeed.py account <url>)
  needsKind,                               // when status is "Needs you": "account" | "question" | "review" | "other"
                                           // (other = CAPTCHA, a verification code, anything the user does by hand)
  needsReason,                             // when status is "Needs you": what the user must do, one short sentence
  questions,                               // needsKind "question": [{id, key, q, a, answeredOn, toBank}]. One entry per
                                           // question; `key` is a short slug shared by identical questions at the same
                                           // company so the page asks once. The page fills `a`, `answeredOn`, `toBank`.
  queued,                                  // true = apply to this next (the user clicked Apply next, Account ready,
                                           // saved answers, or approved). Apply clears it when it submits or holds.
  approved,                                // true = the user approved this prepared application ("review" mode)
  checkedOn,                               // YYYY-MM-DD the posting was last confirmed open (jobfeed.py alive)
  actionNeeded, actionDue,                 // a to-do on a job in any status (take an assessment, reply to schedule
                                           // an interview); shows in the page's Needs-you box until the user clicks Done
  resumeFile,                              // filename of the tailored resume used
  resumeBase,                              // which base it was tailored from, e.g. "2@v1" (lane 2, version 1)
  notes,                                   // the user's free-form notes (never overwrite; append with a dated line)
  history: [{date, status, source, evidence}],
  order                                    // display tiebreaker; continue from the highest
}
```

### Statuses

| Status | Meaning |
|---|---|
| Not applied | Found and judged worth considering. |
| Needs you | Blocked on the user. `needsKind` says how: an account to make or sign in to, a question only they can answer, a prepared application to review, or something else they do by hand (CAPTCHA). `needsReason` says what, in one sentence. Follow-ups on applied jobs use `actionNeeded` instead. |
| Applied | Submitted. `appliedOn` set. |
| Screening | Any response that isn't a rejection or an interview: assessment, recruiter questionnaire, recruiter call request. |
| Interviewing | An interview is scheduled or happened. |
| Offer | Offer received. |
| Rejected | Company said no. |
| Passed | The user (or a check) decided not to apply, or the posting closed before applying. |

"Ghosted" is not a status: the page counts Applied jobs with no change after 30 days.

## What the page writes

Every button saves to the database at once; nothing waits for chat. Each change also appends a `history` entry with `source: "you"`.

| Button | Writes |
|---|---|
| Account ready | `accounts/<key>` status "ready"; every open job behind that account: status Not applied, `queued: true`, `needsKind: ""`, `account` |
| Skip company / Skip all (sign-ins) | `accounts/<key>` status "skipped"; those jobs: status Passed. Later jobs on a skipped account are left out by find-jobs and passed by apply. |
| I applied myself (other blocks) | status Applied, `appliedOn` today |
| Save answers | the job's `questions[].a` (plus `answeredOn`, `toBank`); when every question on a job is answered: status Not applied, `queued: true`, `needsKind: ""` |
| Approve submit | status Not applied, `queued: true`, `approved: true` |
| Done, try again (other blocks) | status Not applied, `queued: true` |
| Skip / skip this one | status Passed |
| Apply next / Unqueue, remove | `queued` true, or `queued` and `approved` false |
| Status dropdown | the new status; clears `queued` and `approved` |
| Done (to-dos) | clears `actionNeeded` and `actionDue` |

Runs never undo these. A run that changes a job the user just touched reads the job again first (pinned writes with `if_version` make this automatic).

## Run document

```
{ kind: "Job search" | "Email check" | "Applications" | "Weekly review" | "Setup",
  at: ISO timestamp, date: YYYY-MM-DD, time: "HH:MM",
  summary: "one or two plain sentences",
  items: [{company, title, detail}],          // what was added, changed or submitted
  stats: {...},                              // raw numbers from the run
  problems: ["..."] }                        // anything that failed or needs a look
```
