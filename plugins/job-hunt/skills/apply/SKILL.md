---
name: apply
description: Applies to jobs for the candidate. Builds a resume tailored to each posting from the verified resume bank, drafts answers in the candidate's voice, checks everything against the dossier, fills the application in the user's Chrome, submits according to their approval setting, and updates the Job Search HQ. Also runs sign-in sessions that line up account sign-ups in Chrome tabs. Use when the user pastes a job link, or says "apply to this", "apply to my top jobs", "apply to my queue", "work through my Needs you list", "let's do sign-ins", "I'm signed in to Workday, continue", or when a scheduled application batch starts.
---

# Apply

**Where files are.** With the plugin installed, shared files live in `../../shared/` relative to this skill: `shared/references/` (rules.md, hq-schema.md, ats-playbook.md, connectors.md, voice.md, schedules.md), `shared/scripts/` and `shared/templates/`. When this file is being followed as a RUNBOOK from the HQ (a scheduled run without the plugin), the same references are published at the top level of the HQ artifact (`rules.md`, `hq-schema.md`, …) and the scripts as `scripts/<name>.txt`. Fetch them with `Artifact` `action: "read"`, `paths`, `out_dir`, and drop the `.txt` suffix. If a tool named here isn't available (AskUserQuestion, SendUserMessage, SendUserFile, SearchMcpRegistry, SuggestConnectors), do the same thing in plain text in your reply.

Read `shared/references/rules.md`, `ats-playbook.md`, `voice.md` and `hq-schema.md` first. The rules win over speed and volume, every time.

## 1. Load

1. Find the HQ. Read `settings/prefs`, `settings/dossier`, `settings/answers`, `settings/base_resumes`, `settings/resume_bank` (save it as `resume_bank.json` for the builder) and `state/apply` (if missing, or its date isn't today, start the count at 0). List `jobs` and `accounts`.
2. Scripts: `shared/scripts/build_resume.py` and `form_helpers.js` (or the `.txt` copies published on the HQ).
3. Check Chrome: load the Claude in Chrome tools (read the `chrome-browser` skill if listed) and call `tabs_context_mcp`. If Chrome isn't reachable you can still prepare (steps 3–5) but not submit. In a scheduled run with no Chrome, log that and stop.

## 2. Pick the jobs

The user mostly steers from the HQ page: its buttons set `queued`, `approved`, answered `questions` and `accounts/<key>` status (hq-schema.md "What the page writes"). Read those first.

- **A link or a named job:** find it in the tracker by URL or company + title. If it isn't there, add it (judge fit as find-jobs does) before applying.
- **Batch ("apply to my top jobs", "apply to my queue", scheduled):** in this order, until `prefs.dailyCap` minus today's count is reached:
  1. `queued: true` jobs (status Not applied): `approved` ones first, then by fit.
  2. Not applied jobs whose `account` has `accounts/<key>` status "ready".
  3. Other Not applied jobs: fit Strong, then Possible, then Stretch if `prefs.allowStretch` (at most one in five); `applyRoute` `no_account`, or `check` once resolved (open the posting, find the employer's own application per ats-playbook.md "Routing", update `url`, `applyRoute` and `account`, then continue if Claude can now apply); newest `foundOn` first.
  Skip a company once it has `perEmployerCap` open applications (Applied, Screening or Interviewing).
- **"I'm signed in to X" / "continue X":** set `accounts/<key>` to "ready" for that company's account (as the page's Account ready button does), then apply to its open jobs.
- **"Submit X" or an `approved` job:** reuse the resume and answers saved in that job's `notes`. If the resume file is no longer in this session, rebuild it from the same spec, which the notes record. Show the answers if the user is live and the job isn't `approved`, then fill and submit.
- **"Let's do sign-ins":** run a sign-in session (section 10) first, then apply to whatever it unlocked.
- **Never** apply to a posting that's already Applied or beyond (match by URL and by company + title).

## 3. Per job: read the posting

Get the full description (the ATS JSON via `jobfeed.py` sources, WebFetch, or the page in Chrome). If it's closed or gone, set status Passed with evidence "Posting closed" and move on. Re-check fit against the dossier. If the real requirements make it a clear mismatch, set Passed with a one-line reason instead of applying.

Route it with ats-playbook.md. For an account site, get the key with `jobfeed.py account <url>` and set `account` on the job:
- `accounts/<key>` is "ready" (or the user just said they're signed in): open the application in Chrome. If a sign-in or create-account screen appears instead of the form, the session has ended: set `accounts/<key>` to "expired", put every queued job behind it back to "Needs you" (`needsKind: "account"`, `queued: false`, reason "Sign in to your <Company> <system> account again"), and move on.
- `accounts/<key>` is "skipped": the user doesn't want that account. Set status Passed, evidence "Account skipped", and move on.
- Otherwise: status "Needs you", `needsKind: "account"`, `needsReason: "Needs your <Company> <system> account"`. The page groups these by account with the buttons the user needs; don't ask about them one by one in chat.

## 4. Tailored resume (every application, no exceptions)

Start from the job's lane base in `settings/base_resumes`. If the lane has no base, use the closest lane's and say so in the notes. Copy it to a new spec JSON (format in `build_resume.py`) and tailor it to this posting:
- Rewrite the summary's first sentence around what this posting asks for most, using its wording where it's true for the candidate.
- Reorder and reword the skills lines so the posting's must-haves the candidate really has come first.
- Swap or reorder bullet keys from the bank so the most relevant work leads. Pick the allowed title closest to the posting.
- Choose the 1–3 projects closest to the posting's work.
- Set a new `file` name for this job, and record `resumeBase` as `"<lane>@v<version>"`.

If the posting calls for a change the bank can't support truthfully, leave it out. Never stretch a claim to match.

Then:
- Check every summary and skills claim against the dossier's skill levels (rules.md section 1). No "Never claim" items; "Basic" stays labelled basic.
- Build: `python3 build_resume.py --bank resume_bank.json --spec spec.json --out-dir resumes`, run from this session's working directory. The Chrome extension's `file_upload` takes files from this session, so a path under the working directory works; if it rejects the path, copy the PDF to the session's outputs folder and retry. Save the spec JSON into the job's notes when holding a job, so it can be rebuilt later. Filename: `<First>_<Last>_<Company>_<Role>` with underscores, no special characters.
- It must report `one_page: true`. If not, drop a bullet or a project and rebuild.
- Extract the PDF text (`pdftotext`) and read it once for typos and stray characters.

## 5. Answers

- Contact and standard facts come from the dossier. Use the form defaults in rules.md section 4.
- Free-text questions: reuse or adapt `settings/answers` in the approved voice (voice.md). New answers stay specific, short and true.
- Salary: the posting's band. If none is posted, the dossier's stated range. Never the floor.
- Answers the user gave on the HQ page (`questions[].a` on this job) are used as written, apart from fixing obvious typos. Where `toBank` is true, add them to `settings/answers` after the application goes in.
- Anything the dossier, the answer bank and the job's answered questions can't answer truthfully: stop this job and hold it as "Needs you" with `needsKind: "question"` and one `questions` entry per open question (`{id, key, q}`). Write `q` so it stands alone on the page: name the company, say if it's required, give the options when the form has a fixed list. Give identical questions at the same company the same `key` (for example `ramp-phone`) so the page asks once for all of them. `needsReason` is a one-line summary. When re-holding a job that already has `questions`, keep the answered entries and add the new ones. Move on. Never guess.

## 6. Fill, check, submit

1. Open the application in a new tab and fill it per ats-playbook.md (upload the resume first, then click and type each field, then zoom-check choices).
2. Pre-submit check: run `__formcheck()` from form_helpers.js, scroll and zoom through the whole form, and compare every value with the dossier. Any contradiction or untraceable claim means hold (rules.md section 2): "Needs you", `needsKind: "question"`, with a `questions` entry that states the conflict and asks which is right.
3. Approval:
   - `approvalMode: "auto"`: submit.
   - `"review"`, live: show the user the role, the resume file, and every free-text answer and choice; submit when they say yes.
   - `"review"`, scheduled: don't leave a half-filled form. Save the prepared answers in the job's `notes` (append a dated block), set "Needs you" with `needsKind: "review"` and reason "Ready to submit: review the answers in the notes", and move on. The page's Approve submit button queues it with `approved: true`.
   - A job with `approved: true` is submitted after the dossier check, in either mode, provided the answers going in are the ones saved in its notes. If anything had to change (the form changed, a new question), hold it for review again.
4. CAPTCHA or bot check: stop and ask the user to complete it (live), or set "Needs you" with `needsKind: "other"` and reason "CAPTCHA on the application: open it, complete the check, then click Done, try again" (scheduled). Never attempt it.
5. After submit, confirm success (playbook step 10). If it's unclear, keep the status Not applied and note what happened. Never resubmit blindly.

## 7. Record

For each submitted application, update the job document: `status: "Applied"`, `appliedOn` and `statusUpdatedOn` set to today, `queued: false`, `approved: false`, `needsKind: ""`, `resumeFile`, `resumeBase`, append to `history` `{date, status: "Applied", source: "apply", evidence: "<ATS> confirmation"}`, and append to `notes` a dated line with the salary answer and any notable answer. Increment `state/apply`. Add any newly written free-text answer to `settings/answers` under "Company-specific answers already given". Send the resume PDF to the user (SendUserFile) when they're live.

Every hold also sets `queued: false` and `approved: false` (an approval covers only what the user saw). Write job changes with `if_version` from your read: if the user changed the job on the page meanwhile, re-read it and keep their change.

## 8. Referral nudge (Strong fits)

While on the posting or the company's LinkedIn job page, note any connections or alumni the user has there. For Strong fits, draft a short note per voice.md "Outreach drafts" and either show it (live) or set `actionNeeded: "Send referral note to <Name>"` with the draft in `notes`. Never send it.

## 9. Close out

Close every tab you opened. Write a `runs` document (`kind: "Applications"`) listing submitted, held (with reasons) and skipped jobs. Report in a few lines: submitted N (companies), held M (what each needs), anything odd.

## 10. Sign-in sessions ("let's do sign-ins")

The user makes the accounts; Claude lines them up so it takes one sitting.
1. From the jobs, group open account jobs by `account` (the page's Sign-ins list), biggest first. Ask which to do now (AskUserQuestion, multi-select, at most 4 per question; offer "the top 5" as the first option).
2. For each chosen account, open one of its postings in a new Chrome tab and click through to the sign-in or create-account screen (Workday: Apply, then Apply Manually). Stop there. Never type an email, password or code, and never click "Create account" or "Sign in".
3. Tell the user which tabs are open and to make each account, then click **Account ready** on the HQ (or say "done"). Don't drive Chrome while they're typing in it: wait for their reply.
4. On "done", set those `accounts/<key>` to "ready" (if the page hasn't already), queue their jobs, close your tabs, and apply to them (section 2, batch).

Run-log documents follow hq-schema.md "Run document" exactly (`kind`, `at` ISO timestamp, `date`, `time`, `summary`, `items`, `stats`, `problems`); the HQ page orders the log by `at`.
