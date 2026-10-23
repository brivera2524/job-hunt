---
name: find-jobs
description: Searches for new job openings that fit the candidate everywhere it lawfully can, from thousands of company job boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, BambooHR, Breezy, Rippling, Teamtailor, Workday), job aggregators (The Muse, Himalayas, Hacker News Who is hiring, remote boards, optionally Google Jobs, Adzuna and USAJOBS), Indeed, ZipRecruiter and Dice, and the user's LinkedIn and other job alert emails, then judges each against the search profile and adds the good ones to the Job Search HQ tracker. Use when the user says "find me jobs", "run my job search", "check for new jobs", "search Indeed for…", "add more companies to my watchlist", or when a scheduled job-search run starts.
---

# Find jobs

**Where files are.** With the plugin installed, shared files live in `../../shared/` relative to this skill: `shared/references/` (rules.md, hq-schema.md, ats-playbook.md, connectors.md, voice.md, schedules.md), `shared/scripts/` and `shared/templates/`. When this file is being followed as a RUNBOOK from the HQ (a scheduled run without the plugin), the same references are published at the top level of the HQ artifact (`rules.md`, `hq-schema.md`, …) and the scripts as `scripts/<name>.txt`. Fetch them with `Artifact` `action: "read"`, `paths`, `out_dir`, and drop the `.txt` suffix. If a tool named here isn't available (AskUserQuestion, SendUserMessage, SendUserFile, SearchMcpRegistry, SuggestConnectors), do the same thing in plain text in your reply.

Read `shared/references/rules.md`, `hq-schema.md` and `connectors.md` first. When run on a schedule, nobody is watching: never ask questions, decide and log.

## 1. Load state

1. Find the HQ (hq-schema.md, "Finding the HQ").
2. Read `settings/profile`, `settings/config`, `settings/page` and `state/seen` (note `state/seen`'s version). Write the config to `config.json` and the seen entries to `seen.json` as `{key: date}`.
3. List the `jobs` collection with `out_dir` (limit 1000; page with the cursor if there are more). Build `tracker.json` as `[{company, title, url}]` and note the highest job number and `order`. List `accounts` too.
4. Scripts: use `shared/scripts/jobfeed.py` from the plugin. If it isn't available, read `scripts/jobfeed.py.txt` from the HQ's published files and save it as `jobfeed.py`.

## 2. Company boards and aggregators

```
cp seen.json seen.before.json
python3 jobfeed.py run --config config.json --seen seen.json --tracker tracker.json --out leads.json
```
One command covers the watchlist, the bulk board lists (`bulk_lists`), and every aggregator that's switched on (connectors.md "Where jobs come from"). Listings found on aggregators are matched to the employer's own posting where one exists, and boards found that way join the watchlist (`config.json` is updated). It takes about 5 minutes with bulk lists, 1–2 without. Keep the printed summary: `aggregator_rows`, `resolved_to_employer`, `boards_added` and `aggregator_problems` go into the run log.

If more than a quarter of the watchlist boards are unreachable (`boards_unreachable` against `watchlist_boards`; the bulk lists always have some dead boards, ignore `bulk_unreachable`), the network is probably blocked: restore `seen.before.json` over `seen.json`, empty `leads.json` (`[]`), note it as a problem, and carry on with step 3. The connectors and email don't depend on board access, and restoring means those postings get judged on a later run instead of being marked seen. An aggregator that returned nothing is listed in `aggregator_problems`; note it and carry on.

Older configs lack `search_terms`, `location`, `aggregators` and `bulk_lists`. If they're missing, fill `search_terms` from the profile's lanes (5–10 short role phrases), `location.metro` from `settings/page.regions.local`, and copy `aggregators` and `bulk_lists` from `shared/templates/config_template.json` (keyless ones only), then save `settings/config` at the end (step 6.2) and mention it in the report.

## 3. Job-board connectors (Indeed, ZipRecruiter, Dice)

Follow connectors.md "Using a job-board connector": build queries from the profile's lanes and locations, collect results into `connector_leads.json`, resolve each to the employer's own posting (probing new companies onto the watchlist as you go), then:
```
python3 jobfeed.py ingest --config config.json --seen seen.json --tracker tracker.json --input connector_leads.json --out leads.json
```
A connector that's missing or erroring gets skipped and noted in the run's `problems`.

## 3b. Job alert emails (LinkedIn, Indeed, Glassdoor…)

If Gmail is connected, follow connectors.md "Job alert emails": collect the jobs in alert emails since the last run into `alert_leads.json` and run `jobfeed.py ingest ... --input alert_leads.json --out leads.json`. This is how LinkedIn-only and Glassdoor-only jobs reach the tracker. Never open LinkedIn or Glassdoor pages with a tool to read them. No Gmail: skip and note it.

## 4. Judge every lead

When there are more than about 80 leads (a first run with bulk lists can have over a thousand), triage first: `python3 jobfeed.py peek leads.json` prints one line per lead. Drop the clear misfits by title, company and location, then read the descriptions of the rest in chunks (load `leads.json` in Python and print the ones you kept). On a first run, focus on the newest postings and the Strong-looking titles, and cap additions as below; the rest are marked seen, so record in the run's `problems` how many were skipped unread ("N leads not read in full on the first run").

Read each remaining lead's description and decide Strong, Possible, Stretch or leave out, using the profile's fit labels. Assign each keeper the lane it fits best. Its base resume will be the starting point when applying. A job that fits no lane is usually a leave-out; keep it as lane 0 only if it's a Strong fit anyway. Also:
- Leave out anything the profile's dealbreakers rule out. Read the description, not just the title: "solutions engineer" roles with quotas are sales; "contract" or part-time gigs are out unless the profile allows them.
- `flags` in each lead highlight words like quota, commission, clearance or relocation. Check them.
- `years` is a rough regex guess (it can pick up "25+ years in business"); read the real requirement.
- Hacker News leads (`source: "hn"`) have the whole first line of the comment as their title and company. Write the real company and role title in the job document, and if the comment names several roles, add each one that fits (same URL is fine).
- `also_on` lists the other places the same job was found. `listing_url` is where it was first seen when `url` was resolved to the employer.
- When unsure between two labels, pick the lower one.
- A typical scheduled run keeps 0–10 jobs. A first run can keep more; keep only Strong and Possible if more than 30 qualify.

For each keeper, write a job document (hq-schema.md) with: the real company name (not the board slug), title, `url` (the employer's posting), location in plain words, `region` (`local` or `remote`, matching `settings/page.regions`), pay as posted, `years` as the posting states it, fit and fitRank, lane, a one-sentence `note` (why it fits and the main gap, plain language), `status: "Not applied"`, `applyRoute` from the lead's `apply_route`, `account` for `needs_account` jobs (`jobfeed.py account <url>`), `source` (the lead's `source`: where it was found), `foundOn: today`, `checkedOn: today`, `top: false`, `order` continuing from the highest, `notes: ""`, and `history: [{date, status: "Not applied", source: "search", evidence: "<source> run"}]`.

Account-required jobs (`applyRoute: "needs_account"`) are added like any other; they appear on the HQ page's Sign-ins list grouped by account, so the user can make one account for several jobs. If `accounts/<key>` is already "ready", also set `queued: true` so they show in the page's Apply next. If it's "skipped", leave the job out: the user decided against that account. Their note doesn't need to mention signing in. Jobs still on a job-board link after step 2–3's matching: if the link is a job board's own posting (LinkedIn, Indeed, ZipRecruiter, Dice, Glassdoor, Wellfound, Built In…), add the job as **apply-yourself** right away: `applyRoute: "manual"`, status "Needs you", `needsKind: "manual"`, `needsReason` "Only listed on <board> (<its apply button>): Claude preps the resume and answers, you submit", `kit: {where, listingUrl: url}`. Upkeep keeps looking for the employer's posting and switches it back if one turns up. Other job-board links (aggregators like Himalayas or The Muse, which send you on to the employer) stay `applyRoute: "check"`, and the note says so.

Write all keepers in one `batch` (split at 50).

## 5. Upkeep of jobs already tracked

Keep the open list honest so the user's attention goes to real openings.
1. **Closed postings.** Collect open jobs (Not applied or Needs you) whose `checkedOn` is missing or older than 7 days, at most 150 per run, oldest first, into `check.json` as `[{id, url}]`. Run `python3 jobfeed.py alive --input check.json --out alive.json`. For `alive: false`: status Passed, `queued: false`, `approved: false`, `needsKind: ""`, history evidence "Posting closed (<why>)". For `alive: true`: set `checkedOn: today`. `null` means it couldn't tell: leave the job alone.
2. **Job-board links.** Collect every open job with `applyRoute: "check"`, plus apply-yourself jobs (`applyRoute: "manual"`) not yet applied to, into `check_leads.json` (`[{id, company, title, url}]`) and run `python3 jobfeed.py resolve --config config.json --input check_leads.json`. Rows whose `url` changed were found on the employer's board: update `url`, `applyRoute` (from the new URL), `account`, and note it in history; an apply-yourself job found this way also goes back to status Not applied with `needsKind: ""` and `queued: true` (Claude can apply now), keeping `kit` for reference. For up to 10 of the rest, Strong and Possible first, look by hand (web-search "<company> careers", probe the careers page, `board --grep`). Still not found after 7 days: the job is only on a job board, so it becomes an **apply-yourself** job: `applyRoute: "manual"`, status "Needs you", `needsKind: "manual"`, `needsReason` "Only listed on <board> (<its apply button, e.g. Easy Apply>): Claude preps the resume and answers, you submit", and `kit: {where: "<board> <apply type>", listingUrl: <url>}`. The apply skill fills in the rest of the kit (apply section 11). Never Pass a job just because it's only on a job board. Account sites (Workday, Apple and the like) are never "check": if a job has `applyRoute: "check"` but `jobfeed.py account <url>` gives route `needs_account`, just fix the route and set `account`.
3. **Accounts.** Any job with `applyRoute: "needs_account"` and no `account`: set it from `jobfeed.py account <url>`.
Write these changes in batches with `if_version`, and count them in the run's `stats` (`closed`, `resolved`, `dropped`).

## 6. Save state and log

1. **Seen:** convert `seen.json` back to `{entries: ["key|date"], updated: today}`, drop entries older than 120 days, and `set` `state/seen` with the version from step 1. On a version conflict, re-read, merge (union of both), and write again.
2. **Config:** if probes added boards (watchlist length changed), `set` `settings/config` from the updated `config.json`.
3. **Run log:** `set` a `runs` document (`kind: "Job search"`) with a summary sentence, `items` for each job added (`{company, title, detail: "<fit> · <source>"}`), `stats` (boards, bulk boards, scanned, aggregator rows by source, alert-email rows, matched, resolved to employer, boards added, already seen, too senior, too old, connector rows, kept, closed, resolved, made apply-yourself, dropped), and `problems` (including `aggregator_problems`).

## 7. Report

One short message: how many jobs were added and from where (for example "9 new: 5 company boards, 2 Hacker News, 2 LinkedIn alerts"), the Strong ones by company and title, how many are apply-yourself jobs waiting, how many closed postings were cleared, and any problem (for example a connector that wasn't available). If nothing was added, say so in one line. In a scheduled run, send it with SendUserMessage (load it via ToolSearch if needed).

## Growing the watchlist (when asked, or weekly)

- Companies that show up on aggregators, connectors or alert emails are matched to their boards automatically, and found boards join the watchlist.
- `bulk_lists` scans the public board lists in full each run; turn it off (`[]`) if runs are too slow.
- To add a company by hand: `python3 jobfeed.py probe --config config.json --company "Name" <careers URL or slug>`. Probe knows Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, BambooHR, Breezy, Rippling, Gem, Teamtailor, Pinpoint, Personio and Workday.
- To find more local employers: web-search lists of the metro's largest employers and companies in the user's field, find their careers pages, probe them, then save `settings/config`.
- Boards that stay unreachable for a week (shown in the run summaries) have usually moved to a different job site. Re-probe the company name or remove the entry.

Run-log documents follow hq-schema.md "Run document" exactly (`kind`, `at` ISO timestamp, `date`, `time`, `summary`, `items`, `stats`, `problems`); the HQ page orders the log by `at`.
