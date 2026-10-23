# Changelog

## 2026-10-23 (0.4.0)
- **Many more job sources.** New company-board types: Workable, Recruitee, BambooHR, Breezy, Rippling, Gem, Teamtailor, Pinpoint, Personio. Aggregators with no key needed: SmartRecruiters (searches every company on it), The Muse, Himalayas, Remote OK, Remotive, Jobicy, We Work Remotely, Hacker News "Who is hiring?". With free keys: Adzuna, USAJOBS, Jooble. On free tiers: Google Jobs via SerpApi or JSearch, which covers LinkedIn, Indeed and Glassdoor listings.
- **Bulk board lists.** `bulk_lists` scans about 12,000 more Greenhouse, Lever, Ashby and Recruitee boards from a public list each run.
- **Matching to the employer.** Job-board and aggregator listings are matched to the employer's own posting automatically (`run`, `ingest`, new `resolve` command). Every board found this way joins the watchlist.
- **Job alert emails.** find-jobs reads LinkedIn, Indeed, Glassdoor and other alert emails through Gmail, the terms-safe way to get LinkedIn jobs. Setup gives ready-made alert links to click.
- **Apply yourself.** Jobs only on LinkedIn Easy Apply, Indeed Apply and the like become apply-yourself jobs instead of being passed. Claude prepares a kit (tailored resume uploaded to the HQ, copyable answers, cover note). The HQ page has an "Apply yourself" section with Open listing, Copy, I applied, and "Let Claude apply there" for when you find the employer's own posting.
- New `jobfeed.py` commands: `sources`, `resolve`, `peek`. `probe` and `board` know every new ATS. New `max_age_days` filter. USAJOBS is handled as an account (one Login.gov account covers every federal job).
- The HQ now needs the `assets` capability, so run "refresh job hunt setup" once after updating.

## 2026-10-20 (0.3.0)
- HQ page: Needs-you split into Sign-ins (one card per account with Account ready / Skip company), Questions (answer on the page; identical questions asked once), Ready to submit, Other blocks and To-dos.
- Apply-next queue, run-status strip with warnings when a scheduled task stops, compact list view.
- Apply reads the page's choices; "let's do sign-ins" lines up create-account screens in Chrome tabs.
- Job searches clear closed postings (`jobfeed.py alive`) and resolve job-board links to employer postings.
- `jobfeed.py account`: works out which account a posting needs.

## 2026-10-19 (0.2.x)
- First shareable version: setup with import mode, base resumes per role group, twice-daily search across company boards, Workday, Indeed, ZipRecruiter and Dice, email checks, weekly review.
