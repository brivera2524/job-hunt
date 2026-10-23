# Connectors this plugin uses

All are claude.ai connectors the user turns on once (Settings → Connectors) and enables in the chat that creates the scheduled tasks. A scheduled task only gets the connectors that were enabled in the session that created it, so create or recreate schedules from a chat where all of them are on.

| Connector | Used by | What for |
|---|---|---|
| Indeed | find-jobs | Job search across Indeed (tools such as `search_jobs`, `get_job_details`) |
| ZipRecruiter | find-jobs | Job search (`search_jobs`); no login needed |
| Dice | find-jobs | Tech job search (`search_jobs`); no login needed |
| Gmail | check-email, find-jobs | Read application emails to update statuses, and job alert emails (LinkedIn, Indeed, Glassdoor…) as a job source. Read-only use: never send, reply, label or delete. |
| Claude in Chrome (extension) | apply | Fill and submit applications in the user's real browser |

## Where jobs come from

The goal is every relevant posting, wherever it's listed, with as much of it as possible reachable on the employer's own site where Claude can apply.

| Layer | What it covers | How |
|---|---|---|
| Watchlist boards | Companies the user cares about (seed list, local employers, everything discovered by earlier runs) | `jobfeed.py run`, config `watchlist` |
| Bulk board lists | ~12,000 more companies on Greenhouse, Lever, Ashby and Recruitee, from the public, MIT-licensed lists at github.com/kalil0321/ats-scrapers | `jobfeed.py run`, config `bulk_lists` (adds 3–4 minutes) |
| Keyless aggregators | SmartRecruiters (all companies at once), The Muse, Himalayas, Remote OK, Remotive, Jobicy, We Work Remotely, Hacker News "Who is hiring?" | `jobfeed.py run`, config `aggregators` |
| Keyed aggregators (optional) | Adzuna, USAJOBS, Jooble (free keys); Google Jobs via SerpApi or JSearch (free tiers of 250 and 200 calls a month, which already include LinkedIn, Indeed and Glassdoor listings) | add keys under config `aggregators.<name>` |
| Job-board connectors | Indeed, ZipRecruiter, Dice | "Using a job-board connector" below |
| Job alert emails | LinkedIn, Indeed, Glassdoor, ZipRecruiter, Wellfound, Built In, Handshake, Welcome to the Jungle and any other site that emails alerts | "Job alert emails" below |

`jobfeed.py sources --config config.json` shows which aggregators are on and which still need a key.

**Every listing found on a job board or aggregator is matched to the employer's own posting automatically** (`run` and `ingest` do it; `jobfeed.py resolve` does it for a file). The match checks watchlist boards and probes likely board names on each supported ATS. Every board found this way joins the watchlist, so each run widens the next.

**Never scraped, by rule:** LinkedIn, Glassdoor, Indeed's website, Wellfound, Built In and other sites whose terms ban bots. LinkedIn's User Agreement (section 8.2) bans scraping and automated access. Indeed's terms ban scraping and automating Indeed Apply. Their jobs reach the tracker only through the official connector, the user's own alert emails, or Google Jobs, and a job that can only be applied for there becomes an "apply yourself" job (apply skill, section 11).

**API keys** live in `settings/config` in the HQ, which is private to the user. Never print them in a run log or message.

## Job alert emails

The one terms-safe way to get LinkedIn's (and Glassdoor's, Wellfound's…) listings is the alerts those sites send the user. Setup helps the user create saved-search alerts on each board (daily, for each lane's main title, in the metro and remote). find-jobs reads them:

1. Load the Gmail tools. Search since the last job search (`state/seen.updated`, with one day of overlap; 3 days if missing), for example:
   `from:(jobalerts-noreply@linkedin.com OR jobs-noreply@linkedin.com OR alert@indeed.com OR noreply@glassdoor.com OR ziprecruiter.com OR wellfound.com OR builtin.com OR joinhandshake.com OR welcometothejungle.com OR otta.com OR dice.com OR jobs-listings@google.com)`
   plus `subject:("job alert" OR "jobs for you" OR "new jobs" OR "recommended jobs")`.
2. Open each alert with `get_thread` (`PLAIN_TEXT`). Each lists several jobs with title, company, location and a link. Collect them into `alert_leads.json` in the connector-lead shape (`{company, title, url, location, source}`), with `source` like `linkedin-alert`. Keep the board's link as `url`; strip tracking parameters but keep the job id (LinkedIn: `linkedin.com/jobs/view/<id>`; Indeed: `jk=<id>`).
3. Run `jobfeed.py ingest --input alert_leads.json` (it resolves each to the employer's posting and dedupes). Don't fetch LinkedIn or Glassdoor pages to get descriptions. For a lead with no employer posting, judge from the alert's text and the company's own site, and keep the job if the title and company fit.
4. Read only. Alert emails stay in the inbox untouched. check-email ignores them.

## Using a job-board connector

Tool names and parameters can change, so load the tools with ToolSearch (for example the query `indeed search jobs`) and read each tool's schema before calling it. Don't guess argument names.

1. **Build queries from the profile.** One query per target role keyword (from the profile's lanes) per location: the user's metro, plus "remote" when the profile allows remote. Keep it to about 12 queries per connector per run. Filter to recent postings (last 3–7 days) when the tool supports it.
2. **Collect results** into `connector_leads.json` as a list of `{company, title, url, location, description, pay, posted, source}`, where `source` is `indeed`, `ziprecruiter` or `dice`. Fetch details (`get_job_details` or similar) only for results whose title passes a quick look, to save calls.
3. **Resolve to the employer's own posting.** The Indeed, ZipRecruiter and Dice "easy apply" paths must not be automated (rules.md section 3), and the employer's posting is where Claude can apply.
   - If the detail shows an external apply URL on a known ATS (greenhouse, lever, ashby, smartrecruiters, workable, recruitee, bamboohr, breezy, rippling, myworkdayjobs, paylocity…), use it as `url`, keep the board link as `listing_url`, and set `ats`.
   - Otherwise leave the board link as `url`: `ingest` tries the company's boards itself. If it still can't find one and the job looks Strong, try by hand: `jobfeed.py probe --config config.json <slug guess or careers URL>`, then `jobfeed.py board <board URL> --grep "<key title words>"`.
   - If no employer posting can be found, keep the job-board URL (`applyRoute: "check"`) and say so in the note.
4. **Filter, resolve and dedupe** with `jobfeed.py ingest --input connector_leads.json` (same title, location, seniority and seen-before rules as the board feed; it appends to `leads.json`).

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
