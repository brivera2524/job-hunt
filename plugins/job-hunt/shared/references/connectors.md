# Connectors this plugin uses

All are claude.ai connectors the user turns on once (Settings → Connectors) and enables in the chat that creates the scheduled tasks. A scheduled task only gets the connectors that were enabled in the session that created it, so create or recreate schedules from a chat where all of them are on.

| Connector | Used by | What for |
|---|---|---|
| Indeed | find-jobs | Job search across Indeed (tools such as `search_jobs`, `get_job_details`) |
| ZipRecruiter | find-jobs | Job search (`search_jobs`); no login needed |
| Dice | find-jobs | Tech job search (`search_jobs`); no login needed |
| Gmail | check-email | Read application emails to update statuses. Read-only use: never send, reply, label or delete. |
| Claude in Chrome (extension) | apply | Fill and submit applications in the user's real browser |

## Using a job-board connector

Tool names and parameters can change, so load the tools with ToolSearch (for example the query `indeed search jobs`) and read each tool's schema before calling it. Don't guess argument names.

1. **Build queries from the profile.** One query per target role keyword (from the profile's lanes) per location: the user's metro, plus "remote" when the profile allows remote. Keep it to about 12 queries per connector per run. Filter to recent postings (last 3–7 days) when the tool supports it.
2. **Collect results** into `connector_leads.json` as a list of `{company, title, url, location, description, pay, posted, source}`, where `source` is `indeed`, `ziprecruiter` or `dice`. Fetch details (`get_job_details` or similar) only for results whose title passes a quick look, to save calls.
3. **Resolve to the employer's own posting** before anything else. The Indeed, ZipRecruiter and Dice "easy apply" paths must not be automated (rules.md section 3), and the employer's posting is where Claude can apply.
   - If the detail shows an external apply URL on a known ATS (greenhouse, lever, ashby, smartrecruiters, myworkdayjobs, paylocity, workable…), use it as `url` and set `ats`.
   - Otherwise run `jobfeed.py probe --config config.json <company-slug-guess>` (try the company name lowercased without spaces, then with hyphens). If it finds a board, list its matching jobs with `jobfeed.py board <board URL or slug --ats X> --grep "<key title words>"` and use the matching posting's URL. A found board also joins the watchlist automatically, so future runs see that company directly.
   - If no employer posting can be found, keep the job-board URL, set `applyRoute: "check"`, and say so in the note.
4. **Filter and dedupe** with `jobfeed.py ingest --input connector_leads.json` (same title, location, seniority and seen-before rules as the board feed; it appends to `leads.json`).

## Connector notes (tested Oct 2026)

**Dice** (`search_jobs`, `get_job_details`, `get_company`)
- `search_jobs(keyword, location, radius, radius_unit: "mi", posted_date: "THREE" | "SEVEN", employment_types: ["FULLTIME"], employer_types: ["Direct Hire"], workplace_types, jobs_per_page: up to 100, page_number)`.
- A location search also returns remote jobs. Run local searches with `workplace_types: ["On-Site", "Hybrid"]` and a separate remote search with `["Remote"]`.
- Results lean heavily toward staffing agencies and third-party contracts. `employer_types: ["Direct Hire"]` cuts most of them; also drop `employmentType` containing "Third Party" and obvious staffing firms unless the profile allows them.
- Use `guid` (not `id`) for `get_job_details`, which returns the description and skills only. There's no employer apply link, so resolve by company with `probe` / `board` (step 3). `easyApply: true` means Dice's own apply: never automate it.

**ZipRecruiter** (`search_jobs`)
- `search_jobs(job_role, location, country_admin_code: "US", radius_miles, max_posted_minutes_ago: 4320–10080, employment_types: ["FULL_TIME"], seniority_classes: ["NO_EXPERIENCE", "JUNIOR", "MID"] as the profile allows, location_types: ["REMOTE"] for remote searches, offset)`.
- Returns at most 5 jobs per call. Page with `offset` (two or three pages per query is plenty) and pass back the `conversation_id` from the previous result.
- Results give structured salary and `days_ago`, but no description. `job_redirect_url` is blocked from the cloud shell (403), so resolve by company with `probe` / `board`, or open the redirect with WebFetch or in Chrome when it's worth it.
- Expect title noise (manufacturing or lab "QA/QC" roles for a software QA search). The judging step removes them.

**Indeed** (tools such as `search_jobs`, `get_job_details`)
- Not inspected yet. Load with ToolSearch and read the schema first. Apply the same rules: recent postings only, full-time, the user's metro plus a remote search, resolve to the employer, never automate Indeed Apply.

**Disclosure.** The job-board tools ask that results shown to the user note they were found with AI-assisted search and should be verified with the employer. Add one line saying so to any run summary that lists connector-sourced jobs.

## Using Gmail

Load the Gmail tools with ToolSearch (`gmail search threads`). Search previews show only the oldest messages in a thread, so call `get_thread` (format `PLAIN_TEXT`) on every thread you classify. Never call tools that send, reply, forward, label, archive or delete.

## When a connector is missing

Skip that source, finish the run with what's available, and list the missing connector in the run's `problems` so the user sees it in the Activity tab. Don't stop the whole run.
