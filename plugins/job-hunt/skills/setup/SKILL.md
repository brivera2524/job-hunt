---
name: setup
description: Sets up an AI-run job search from scratch or imports one already in progress. Interviews the candidate to build a verified dossier, search profile, answer bank and resume bank, creates the Job Search HQ tracker page, imports an existing tracker, connects Indeed, ZipRecruiter, Dice and Gmail, and schedules daily job searches and email checks. Use when the user says "set up my job search", "start job hunting", "import my job tracker", "connect my tracker", "set up the job hunt plugin", or "refresh job hunt setup".
---

# Job Hunt setup

**Where files are.** With the plugin installed, shared files live in `../../shared/` relative to this skill: `shared/references/` (rules.md, hq-schema.md, ats-playbook.md, connectors.md, voice.md, schedules.md), `shared/scripts/` and `shared/templates/`. When this file is being followed as a RUNBOOK from the HQ (a scheduled run without the plugin), the same references are published at the top level of the HQ artifact (`rules.md`, `hq-schema.md`, …) and the scripts as `scripts/<name>.txt`. Fetch them with `Artifact` `action: "read"`, `paths`, `out_dir`, and drop the `.txt` suffix. If a tool named here isn't available (AskUserQuestion, SendUserMessage, SendUserFile, SearchMcpRegistry, SuggestConnectors), do the same thing in plain text in your reply.

Read `shared/references/rules.md` and `shared/references/hq-schema.md` before starting; they apply to everything below.

Setup is a conversation. Tell the user up front what's coming (about 20–30 minutes: a short interview, a few approvals, then it runs a first search) and keep each question small. Use AskUserQuestion for choices. Draft from material the user already has before asking them to type anything.

## 0. Check what already exists

- Call `Artifact` `action: "list"` and look for "Job Search HQ". If one exists, ask: refresh it (republish scripts and runbooks, review schedules, keep all data) or start a new one. **Refresh** reads the existing HQ (`Artifact` `action: "read"`, required before publishing to it), then stages step 6.1's files from the *current* plugin (the new `hq.html` template, keeping the existing page's title suffix such as "· Alex") and publishes them with the existing `url`. Leave `capabilities` out so the stored `db` capability carries over. Never publish without `url` in refresh mode, because that creates a second, empty HQ. Then it reviews schedules (step 9) and brings older data up to the current schema: for open jobs (Not applied, Needs you), derive `applyRoute` and `account` from the URL (step 7), set `needsKind` on Needs-you jobs from their reason (sign-in → "account", "Ready to submit" → "review", CAPTCHA → "other", anything else → "question" with the reason rewritten as `questions` entries), and run the closed-posting check (find-jobs step 5.1). Show the user what changed before writing. Settings are left alone.
- Call `list_triggers` (load via ToolSearch) and note any existing job-search scheduled tasks.

## 1. Connectors

Search the registry (`SearchMcpRegistry`) for Gmail, Indeed, ZipRecruiter and Dice. For any not connected, show them with `SuggestConnectors`. For any connected but off in this chat, ask the user to switch it on here: scheduled tasks inherit only the connectors enabled in the chat that creates them. Check the Claude in Chrome extension with `tabs_context_mcp`; if it isn't reachable, applying will wait until it is, and nothing else is blocked. Don't stall: continue while the user connects things, and confirm before step 9.

## 2. Gather the candidate's material

Ask what they can give you, all optional:
- A current resume (any format), LinkedIn profile text or export, GitHub/portfolio links.
- **Import:** files from an earlier setup or another tool, such as a dossier, answer bank, resume bank (`resume_bank.json`), base resumes (`base_resumes.json`, or earlier base or general resumes as PDFs), search profile, feed config (`config.json`), import notes, or a backup zip. Read every file in full.

**Import mode.** When an imported dossier exists, it is the default answer to everything it covers. Don't re-interview. Don't propose new wording for anything it fixes: allowed titles, required phrasings, confidentiality phrasing, skill levels, salary handling. Ask only about (a) real conflicts between sources (name both versions and ask which is right), (b) required facts that are missing, and (c) items the user flagged as unconfirmed. Use your conversation memory only to fill gaps, never to override the dossier. Put all questions in one numbered list, numbered 1, 2, 3… with no gaps or empty bullets. "ok" should be a valid answer to each.
- **An existing job tracker** to import: a claude.ai artifact URL, a spreadsheet, a CSV, or a pasted list. (Imported in step 7.)

## 3. Build the dossier (ground truth)

Fill `shared/templates/dossier_template.md` from the material, then walk the user through it section by section. The rules:
- Every claim gets the candidate's confirmation. Mark anything unconfirmed and keep it off resumes until it's confirmed.
- Dates come from LinkedIn or offer letters, not memory. Ask which source is the truth when two disagree.
- Ask for honest skill levels (Strong / Working / Basic / Never claim). Push gently: "Could you defend this in a technical interview?"
- Capture the internal facts forms keep asking: work authorization, start date, schedule flexibility, relocation, reasons for leaving, salary handling and a private floor (never stated on forms), confidentiality limits, standing answers.
- Ask about referral network: school and alumni groups, and people they know at companies they'd want.

## 4. Role groups, search profile, voice and answer bank

- **Role groups (lanes).** Work out which groups of roles the candidate can credibly get, from the dossier, not just from what they'd like. Propose 2–4 lanes. For each, give the typical job titles, the dossier evidence that qualifies them (which experience, projects and skills), the usual gaps postings will ask about, and roughly what share of postings in that group they'd fit. Mention any lane they asked for but the dossier doesn't yet support, honestly, with what would close the gap. The user picks the final lanes. Imported lanes stay unless the user wants changes.
- **Profile:** fill `shared/templates/profile_template.md` with the confirmed lanes, plus locations (local metro and/or remote), dealbreakers (for example "no sales"), seniority limits, what they bring, weak spots. Confirm it.
- **Voice:** draft one 80–120 word answer to "Why are you interested in this kind of role?" using `shared/references/voice.md`. Revise until the user says it sounds like them. That's the approved sample.
- **Answer bank:** fill `shared/templates/answers_template.md` with the approved sample plus 3–5 common answers, each approved.

## 5. Resume bank and preferences

- Turn the dossier's verified bullets into a resume bank JSON (format at the top of `shared/scripts/build_resume.py`): every experience with its allowed titles and keyed bullets, every project with keyed bullets, education, contact line. Validate with `python3 build_resume.py --bank resume_bank.json --check`.
- **Base resumes, one per lane.** For each lane, write a base resume spec (same format as a job spec): a summary pitched at that lane, three skills lines in that lane's vocabulary, the best allowed title, and the bullets and projects that lane values most. Build each, check it's one page, and send all of them together (SendUserFile). Revise until the user approves each one. Save them as `settings/base_resumes` (`{"<lane id>": {version: 1, approvedOn, file, summary, skills, experience, projects}}`). Imported base resumes (a `base_resumes.json`, or older base PDFs rebuilt from the bank) are shown for a quick re-approval, not redrafted. Every application still gets its own resume, tailored from its lane's base (apply step 4).
- **Privacy acknowledgements:** most application forms require accepting the employer's privacy or data-processing notice. Ask once whether Claude may accept these on the user's behalf (`acceptPrivacyAck`). If they say no, those applications wait in "Needs you".
- **Preferences** (`settings/prefs`): approval mode (recommend `"review"` for new users: Claude prepares and fills everything, the user OKs each submit; `"auto"` submits after the dossier check), daily cap (default 8), per-company cap (default 2), whether Stretch fits are allowed, timezone.

## 6. Create the HQ

1. Load the `artifact-design` and `artifact-capabilities` skills if they're listed (the page is already designed and themed; publish it as is). Make a folder `hq/` in the working directory and copy into it `shared/templates/hq.html` as `hq/job-search-hq.html`, every file from `shared/scripts/` as `hq/scripts/<name>.txt`, every file from `shared/references/`, and each skill's SKILL.md as `hq/RUNBOOK-<skill>.md`. The Artifact tool only publishes files from the working directory or scratchpad. In the page, keep the `<title>` prefix "Job Search HQ", since other skills find the HQ by it; you may append the user's first name.
2. Publish `hq/job-search-hq.html` with the Artifact tool: `capabilities: {"db": {}}`, `icon: "briefcase"`, a one-line description, and `files` mapping each published path to the staged copy in `hq/` (scripts with `contentType: "text/plain"`):
   - `scripts/jobfeed.py.txt`, `scripts/build_resume.py.txt`, `scripts/form_helpers.js.txt`
   - `rules.md`, `hq-schema.md`, `ats-playbook.md`, `connectors.md`, `voice.md`, `schedules.md`
   - `RUNBOOK-find-jobs.md`, `RUNBOOK-apply.md`, `RUNBOOK-check-email.md`, `RUNBOOK-weekly-review.md`
   Then do the one functional check the Artifact tool asks for: write `settings/page`, list it back, and confirm it's there.
3. Write the settings documents with one `ArtifactData` batch (see hq-schema.md): `settings/page` (title, lanes from the profile, regions `{"local": "<metro name>", "remote": "Remote"}`, weeklyGoal 10), `settings/prefs`, `settings/profile`, `settings/dossier`, `settings/answers`, `settings/resume_bank`, `settings/base_resumes`, and empty state documents: `state/seen` (`{entries: [], updated}`), `state/email` (`{lastCheck: <14 days ago>, processed: []}`) and `state/apply` (`{date: today, count: 0}`). Write large documents via `file_path`.
4. Tell the user the HQ is private to them, and that it holds their dossier, so they should think before sharing it.

## 7. Import an existing tracker (if given)

- **Artifact URL:** read it (`Artifact` read, then `ArtifactData` `list` with `out_dir` on its collections; a tracker usually keeps one collection such as `jobs`). Read every row.
- **Spreadsheet/CSV/list:** read it fully.

Map each row onto the job schema. Keep: company, title, url, location, pay, status, appliedOn, notes, fit and lane when present. Never copy an apply route from the source: derive `applyRoute` and `account` from each URL with `python3 jobfeed.py account <url> ...` (a LinkedIn or Indeed link is "check", never an account). Map statuses: anything interview-like → Interviewing; assessment, phone screen or "in review with recruiter" → Screening; "declined" or "not selected" → Rejected; "withdrew" or "skipped" → Passed; unknown → keep as Applied if there's an applied date, else Not applied. Set `source: "imported"` unless a source exists, `foundOn` to the original date if known, and `history: [{date: today, status, source: "imported", evidence: "Imported from <where>"}]`. Keep existing `j…` ids; otherwise number from `j0001`. Write in batches of 50 (new documents need no `if_version`). Afterwards, list-read the HQ `jobs` collection, compare the count with the source, and report it. Then run the closed-posting check (find-jobs step 5.1) over the imported open jobs, so the user doesn't make accounts for postings that are already gone, and report how many were closed.

## 8. Feed config and watchlist

- Start from `shared/templates/config_template.json`. Rebuild every filter from this user's profile; the template values are only examples. `title_include` comes from the lanes' keywords (keep it broad, since Claude judges fit later). `title_exclude` keeps the seniority words that match their level and adds their dealbreakers. Show the user the exclusion list and confirm it, because a word like "sales", "manager" or "contract" may be exactly what someone else is looking for. `workday_search_terms` gets 5–10 short keywords from their lanes. Fill `local_places` from the metro's city and suburb names, `local_label: "local"`, `max_years_required` and `max_pay_floor` from the seniority limits. Compile every regex in Python to check it.
- Watchlist: if an imported `config.json` exists, use its watchlist. Otherwise start with `shared/templates/seed_watchlist.json` (about 500 tech companies on no-account ATSs), then add local employers: web-search the metro's largest employers and companies in the user's field, find each careers page, and run `python3 jobfeed.py probe --config config.json <careers URL or slug> ...`. The probe accepts Greenhouse, Lever, Ashby and SmartRecruiters slugs or URLs and Workday career-site URLs (`https://<tenant>.wd<N>.myworkdayjobs.com/<site>`). Aim for 20–60 local boards. Use `--company "<Name>"` for one target at a time when you want a proper display name.
- Save as `settings/config` (via `file_path`).
- Run the `find-jobs` skill once now, interactively, so the user sees real results and can correct the fit judgements before schedules take over. Adjust the profile or filters from their feedback.

## 9. Schedules

Follow `shared/references/schedules.md` exactly: check existing tasks, ask before disabling or replacing any, then create the job search, email check and weekly review tasks with the HQ URL filled in. Offer the optional applications task and explain that it runs only while their computer is on with Chrome and the Claude extension running. When each is created, say in one sentence which approval setting it got. Then write `settings/page.schedule` (hq-schema.md) so the page shows when each task runs and warns when one stops running.

## 10. Finish

Give the user: the HQ (already shown as a card), what runs when, and how the page works: Needs you groups sign-ins by account (make the account, click Account ready, and every job behind it is queued), questions are answered right on the page, and Apply next shows what the next run will do. The one next step is usually: "say 'let's do sign-ins' or 'apply to my queue' when you're at your computer". Log a `runs` document with `kind: "Setup"`.

Run-log documents follow hq-schema.md "Run document" exactly (`kind`, `at` ISO timestamp, `date`, `time`, `summary`, `items`, `stats`, `problems`); the HQ page orders the log by `at`.
