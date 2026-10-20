# Application form playbook

Practical knowledge for filling applications in the user's real Chrome through the Claude in Chrome extension. Read the `chrome-browser` skill first if it's listed. Learned from real submissions; update this file when a site behaves differently.

## Routing: can Claude submit this one?

| Where the Apply button leads | Route |
|---|---|
| Greenhouse (`job-boards.greenhouse.io`, `boards.greenhouse.io`, or a company page embedding it) | Claude fills and submits |
| Ashby (`jobs.ashbyhq.com`) | Claude fills and submits |
| Lever (`jobs.lever.co`) | Claude fills and submits |
| SmartRecruiters (`jobs.smartrecruiters.com`) | Claude fills; if it demands sign-in, "Needs you" with `needsKind: "account"` and `account: "smartrecruiters"` |
| Paylocity (`recruiting.paylocity.com`) | Claude fills and submits |
| Workable, BambooHR, JazzHR / applytojob, Breezy, Recruitee, Gem | Usually no account; try, and stop at any sign-in wall |
| Workday (`*.myworkdayjobs.com`, `*.myworkdaysite.com`), Apple (`jobs.apple.com`), iCIMS, Taleo / Oracle, SuccessFactors, UKG / UltiPro, Dayforce, ADP | Needs the user's account: "Needs you" with `needsKind: "account"` until they're signed in, then Claude fills in their session |
| LinkedIn Easy Apply, Indeed Apply, ZipRecruiter 1-click, Dice Easy Apply | Never automate. Find the employer's own posting (company careers page or ATS) and use that. If there is none, "Needs you" with `needsKind: "other"`, saying where it's listed. |

To find the employer's own posting from a job-board listing: look for "Apply on company site"; otherwise search the company's careers page (or run `jobfeed.py probe <company-slug>`) and match the title.

## General method (every site)

1. Open a new tab in the extension's tab group. Never reuse the user's own tabs.
2. Read the form with `get_page_text` plus `read_page` (filter interactive) or `find`. List every field and mark required ones (asterisk).
3. Upload the tailored resume first (`file_upload` on the file input). Many forms parse it and pre-fill fields, which you then correct.
4. Fill text fields with a real click followed by `type`. This is the most reliable method everywhere. A JavaScript value setter works on Greenhouse but silently fails on Ashby.
5. To replace text, use `triple_click` then type. Don't use ctrl+a / cmd+a: on some Macs it types the letter "a".
6. Comboboxes and dropdowns: click to open, type a few letters, then click the matching option. **Never press Enter** inside a Greenhouse form; it submits the form.
7. Radios and checkboxes: click, then zoom-screenshot the group to confirm the right one registered. Ashby and Paylocity sometimes register a neighbouring option.
8. Before submitting, scroll top to bottom and zoom-check every field against the dossier (rules.md section 2). Check the phone number for stray characters.
9. Submit by clicking the button (compute coordinates from a fresh screenshot). If nothing happens, wait two seconds and click once more. Never click submit a third time without checking for a validation error first.
10. Confirm success: a "Thank you / application received" message, or a confirmation email shortly after. Record the job as Applied only after one of these. Ashby can silently block applications, so a confirmation email is the stronger proof.
11. Close the tab.

`shared/scripts/form_helpers.js` holds two page helpers: `__formcheck()` dumps every field's label and current value (good for the pre-submit check on any site), and `__gh(texts, combos)` bulk-fills Greenhouse forms. Load it with `javascript_tool` by pasting the file contents, then call the function.

## Site notes

**Greenhouse.** Text fields accept the native value setter plus input/change/blur events (`__gh` does this). Selects are react-select comboboxes: click, type, then pick the option by click or Tab. The location field is an autocomplete: type the city, wait, click the suggestion. Embedded forms work at `job-boards.greenhouse.io/embed/job_app?for=<board>&token=<job id>`, which avoids company-site wrappers. The demographic section at the end is optional; follow rules.md section 4.

**Ashby.** Use real clicks and typing only. "How did you hear" is a combobox: type, then click the option, then click elsewhere and zoom to confirm it stuck. Yes/No questions are button pairs; zoom-check them. Success shows a green banner.

**Lever.** Plain HTML. The resume file input is hidden: before `file_upload`, make it visible with JavaScript (set `display: block`, `opacity: 1` on `input[type=file][name=resume]`). Submit is at the very bottom; a second click is sometimes needed. Lever may show an hCaptcha: stop and ask the user (rules.md section 3).

**Paylocity.** Untick "Fill out application with my resume" if you want control (autofill still populates work history: check it). Custom dropdowns mis-select easily, so zoom-check each one. The state field wants the two-letter abbreviation. Work-history and education sections are long; fill them from the dossier exactly.

**SmartRecruiters.** Multi-step. Choose the manual application path, never "Apply with LinkedIn/Indeed". If it requires an account, mark "Needs you" with `needsKind: "account"` and `account: "smartrecruiters"` (one account covers every company on SmartRecruiters).

**Workday and other account sites.** Set `account` from `jobfeed.py account <url>`. Until `accounts/<key>` is "ready", mark the job "Needs you" with `needsKind: "account"` and reason "Needs your <Company> <system> account"; the HQ page groups these into one card per account. Once ready, open the posting in a new tab of the same Chrome and fill it. A sign-in screen on a ready account means the session ended: mark the account "expired" (apply skill, step 3). Workday is slow and multi-page: save at each step, and expect a work-history page that must match the dossier exactly. Never enter or change a password, and never create the account.

## Referral check while on the posting

If the job came from LinkedIn, or the user is signed in to LinkedIn, the job page often lists "People you can reach out to" or alumni at the company. Note any first- or second-degree connections or alumni in the job's notes. For Strong fits, draft a short connection note for the user to send (voice.md). Never send it yourself.
