# Job Hunt

An honest, mostly hands-off job search for Claude.

- **Finds jobs twice a day, nearly everywhere they're posted**: about 13,000 company job boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, BambooHR, Breezy, Rippling, Teamtailor and more), Workday career sites of employers you choose, job aggregators (The Muse, Himalayas, Remote OK, Remotive, Jobicy, We Work Remotely, Hacker News "Who is hiring?"), Indeed, ZipRecruiter and Dice, and your LinkedIn, Glassdoor and other job alert emails. Optional free keys add Google Jobs, Adzuna and USAJOBS. Every listing it finds on a job board is matched to the employer's own posting where one exists, and each company it discovers is watched from then on. It judges each posting against your search profile and adds the good ones to your tracker.
- **Makes job-board-only jobs a one-minute task.** LinkedIn Easy Apply, Indeed Apply and the like can't be automated without breaking those sites' rules, so for those jobs Claude prepares a kit instead: a tailored resume to download, every answer ready to copy, and a cover note. You open the listing, paste, submit, and click **I applied**.
- **Applies with a resume built for each job**, from bullets you verified, and checks every answer against your dossier before submitting. Your approval setting decides whether it asks first or submits on its own.
- **Reads your email** (read-only) to mark rejections, assessments, interviews and offers, and flags anything with a deadline.
- **Reviews the week**: what's getting responses, what isn't, and where a referral would help.
- **Keeps everything in one private page**, the Job Search HQ: your tracker, a "Needs you" list, an "Apply next" queue, and a log of every run. You steer from the page with buttons; the next run picks up what you clicked.

## Getting started

Install the plugin, open a new chat, and say **"set up my job search"**. Setup takes about 20–30 minutes: a short interview to build your dossier and search profile, a writing-voice check, a sample resume, then a first search. Bring your resume, and your old tracker if you have one (a claude.ai page, a spreadsheet, or a CSV). It gets imported.

## What to connect

| Connector | Why |
|---|---|
| Gmail | Email checks, and your job alert emails as a job source (read-only) |
| Indeed, ZipRecruiter, Dice | Extra job sources |
| Claude in Chrome (browser extension) | Filling and submitting applications in your own browser |

Turn them on in Settings → Connectors, and switch them on in the chat where you run setup: scheduled runs get only the connectors that were on in that chat.

## The Needs-you list

Things only you can do, sorted by kind:
- **Sign-ins.** Sites like Workday need an account per company. Jobs are grouped by the account they need, biggest payoff first. Make the account, click **Account ready**, and every job behind it is queued. **Skip company** passes them all. Saying "let's do sign-ins" opens the sign-up screens in Chrome tabs so you can make several accounts in one sitting.
- **Questions.** Things your dossier can't answer, with a box to type your answer. Identical questions across one company's jobs are asked once.
- **Ready to submit.** In review mode, prepared applications wait for **Approve submit**.
- **Apply yourself.** Jobs listed only on LinkedIn, Indeed or another job board that Claude may not apply on. Each has the tailored resume, copy buttons for every answer and the cover note, an **Open listing** button and **I applied**. If you spot the job on the company's own site, paste that link and Claude applies there instead.
- **Other blocks.** CAPTCHAs and anything else you do by hand.
- **To-dos.** Follow-ups on jobs you've applied to: assessments, referral notes, replies.

Closed postings are cleared automatically, so you don't make an account for a job that's gone.

## Everyday use

- "Let's do sign-ins" (at your computer, with Chrome open)
- "Apply to my queue" or "Apply to my top jobs"
- "Apply to this: <link>"
- "Prep my apply-yourself jobs"
- "Check my email for job updates"
- "How's my job search going?"

## What it will never do

Create accounts or type passwords, get around a CAPTCHA, scrape LinkedIn or Glassdoor, automate LinkedIn Easy Apply or Indeed Apply, send a message on your behalf, state your private salary floor, or put a claim on a resume that isn't in your dossier. Anything it can't do honestly lands in the "Needs you" list with the reason.

## Requirements

Claude with scheduled tasks, artifacts and the Claude in Chrome extension. Applications run only while your computer is on with Chrome open; searching and email checks run in the cloud.
