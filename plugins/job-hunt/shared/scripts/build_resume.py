#!/usr/bin/env python3
"""Build a tailored one-page resume PDF from a bullet bank and a per-job spec.

  python3 build_resume.py --bank resume_bank.json --spec spec.json --out-dir out/
  python3 build_resume.py --bank resume_bank.json --check          # validate the bank only

Every experience and project bullet comes from the bank, so a tailored resume can
only reorder and select verified wording, never invent it. The summary and skills
lines are written per job and must be checked against the dossier by Claude.

Bank format (resume_bank.json):
{
  "name": "Full Name",
  "contact": ["City, ST", "phone", "email", "github.com/x", "linkedin.com/in/x"],
  "experience": [
    {"id": "acme", "titles": ["QA Analyst", "Test Analyst"],      # allowed title wordings
     "title_note": "",                                             # e.g. " (promoted from X, 2023)"
     "org_line": "Acme Corp (Contract, remote)", "dates": "2023 – Present",
     "bullets": {"key": "Bullet text", ...}}
  ],
  "projects": [
    {"id": "proj", "name": "Project Name", "tag": "Python · github.com/x/y",
     "bullets": {"key": "Bullet text"}}
  ],
  "education": [{"degree": "B.S. Something", "school": "Some University", "dates": "2023"}],
  "certifications": ["optional"],
  "section_order": ["summary", "skills", "experience", "projects", "education"]
}

Spec format (one job):
{
  "file": "Name_Company_Role",                      # output filename without .pdf
  "summary": "2-4 sentences written for this job",
  "skills": [["Label", "comma, separated, items"], ...],
  "experience": [{"id": "acme", "title": "QA Analyst", "bullets": ["key1", "key2"]}],
  "projects": [{"id": "proj", "bullets": ["key"]}],
  "section_order": optional override
}
"""
import argparse, asyncio, html, json, pathlib, re, sys

CSS = """
@page { size: Letter; margin: 0.45in 0.6in; }
* { box-sizing: border-box; }
body { font-family: Carlito, Calibri, 'Liberation Sans', Arial, sans-serif; font-size: 10.2pt; line-height: 1.24; color: #111; margin: 0; }
h1 { font-family: Lora, Georgia, serif; font-size: 20pt; font-weight: 600; margin: 0 0 2pt; letter-spacing: .2pt; }
.contact { font-size: 9.6pt; color: #333; margin-bottom: 7pt; }
.contact span + span::before { content: "  ·  "; color: #888; }
h2 { font-size: 10pt; letter-spacing: 1.2pt; text-transform: uppercase; margin: 8pt 0 3pt; padding-bottom: 1.5pt; border-bottom: 0.8pt solid #333; color: #1a1a1a; }
p.summary { margin: 0; }
.skills div { margin: 0 0 1.5pt; }
.role { display: flex; justify-content: space-between; gap: 8pt; margin-top: 4pt; }
.role .right { white-space: nowrap; color: #333; }
ul { margin: 2pt 0 0 0; padding-left: 13pt; }
li { margin: 0 0 1.6pt; }
.proj { margin-top: 4pt; }
.proj .tag { color: #444; font-size: 9.6pt; }
"""

ONE_PAGE_PX = 970  # content height that fits one Letter page at these margins


def esc(s):
    return html.escape(str(s), quote=False)


def validate(bank, spec=None):
    errs = []
    for k in ("name", "contact", "experience", "education"):
        if k not in bank:
            errs.append(f"bank missing '{k}'")
    for i, e in enumerate(bank.get("experience", [])):
        for k in ("id", "titles", "org_line", "dates", "bullets"):
            if not e.get(k):
                errs.append(f"experience #{i + 1} missing '{k}'")
    for i, p in enumerate(bank.get("projects", [])):
        for k in ("id", "name", "bullets"):
            if not p.get(k):
                errs.append(f"project #{i + 1} missing '{k}'")
    for i, ed in enumerate(bank.get("education", [])):
        for k in ("degree", "school"):
            if not ed.get(k):
                errs.append(f"education #{i + 1} missing '{k}'")
    exp = {e.get("id"): e for e in bank.get("experience", [])}
    proj = {p.get("id"): p for p in bank.get("projects", [])}
    if spec:
        if spec.get("file") and not re.fullmatch(r"[A-Za-z0-9_.-]+", spec["file"]) or ".." in spec.get("file", ""):
            errs.append("spec 'file' may only use letters, digits, '_', '-', '.' (no paths)")
        for k in ("file", "summary", "skills", "experience"):
            if k not in spec:
                errs.append(f"spec missing '{k}'")
        for e in spec.get("experience", []):
            src = exp.get(e["id"])
            if not src:
                errs.append(f"unknown experience id '{e['id']}'")
                continue
            title = e.get("title") or src["titles"][0]
            if title not in src.get("titles", []):
                errs.append(f"title '{title}' not allowed for '{e['id']}' (allowed: {src.get('titles')})")
            for b in e.get("bullets", []):
                if b not in src["bullets"]:
                    errs.append(f"unknown bullet '{b}' in experience '{e['id']}'")
        for p in spec.get("projects", []):
            src = proj.get(p["id"])
            if not src:
                errs.append(f"unknown project id '{p['id']}'")
                continue
            for b in p.get("bullets", []):
                if b not in src["bullets"]:
                    errs.append(f"unknown bullet '{b}' in project '{p['id']}'")
    return errs


def render(bank, spec):
    exp = {e["id"]: e for e in bank["experience"]}
    proj = {p["id"]: p for p in bank.get("projects", [])}
    out = [f"<h1>{esc(bank['name'])}</h1>",
           '<div class="contact">' + "".join(f"<span>{esc(c)}</span>" for c in bank["contact"]) + "</div>"]
    order = spec.get("section_order") or bank.get("section_order") or ["summary", "skills", "experience", "projects", "education"]
    for sec in order:
        if sec == "summary" and spec.get("summary"):
            out += ["<h2>Summary</h2>", f'<p class="summary">{esc(spec["summary"])}</p>']
        elif sec == "skills" and spec.get("skills"):
            out.append('<h2>Skills</h2><div class="skills">')
            out += [f"<div><b>{esc(l)}:</b> {esc(v)}</div>" for l, v in spec["skills"]]
            out.append("</div>")
        elif sec == "experience" and spec.get("experience"):
            out.append("<h2>Experience</h2>")
            for e in spec["experience"]:
                src = exp[e["id"]]
                title = e.get("title") or src["titles"][0]
                out.append(f'<div class="role"><div class="left"><b>{esc(title)}</b>{esc(src.get("title_note", ""))}, '
                           f'{esc(src["org_line"])}</div><div class="right">{esc(src["dates"])}</div></div>')
                if e.get("bullets"):
                    out.append("<ul>" + "".join(f"<li>{esc(src['bullets'][b])}</li>" for b in e["bullets"]) + "</ul>")
        elif sec == "projects" and spec.get("projects"):
            out.append("<h2>Projects</h2>")
            for p in spec["projects"]:
                src = proj[p["id"]]
                tag = f' <span class="tag">· {esc(src["tag"])}</span>' if src.get("tag") else ""
                out.append(f'<div class="proj"><b>{esc(src["name"])}</b>{tag}</div>')
                out.append("<ul>" + "".join(f"<li>{esc(src['bullets'][b])}</li>" for b in p["bullets"]) + "</ul>")
        elif sec == "education" and bank.get("education"):
            out.append("<h2>Education</h2>")
            for ed in bank["education"]:
                out.append(f'<div class="role"><div class="left"><b>{esc(ed["degree"])}</b>, {esc(ed["school"])}</div>'
                           f'<div class="right">{esc(ed.get("dates", ""))}</div></div>')
        elif sec == "certifications" and bank.get("certifications"):
            out += ["<h2>Certifications</h2>", "<ul>" + "".join(f"<li>{esc(c)}</li>" for c in bank["certifications"]) + "</ul>"]
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(bank['name'])} Resume</title>"
            f"<style>{CSS}</style></head><body>{''.join(out)}</body></html>")


async def build(bank, specs, out_dir):
    from playwright.async_api import async_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch()
        except Exception:
            browser = await pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 701, "height": 960})
        for spec in specs:
            await page.set_content(render(bank, spec), wait_until="load")
            pdf = out_dir / f"{spec['file']}.pdf"
            await page.pdf(path=str(pdf), format="Letter", print_background=True,
                           margin={"top": "0.45in", "bottom": "0.45in", "left": "0.6in", "right": "0.6in"})
            h = await page.evaluate("document.body.scrollHeight")
            results.append({"file": str(pdf), "height": h, "one_page": h <= ONE_PAGE_PX})
        await browser.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True)
    ap.add_argument("--spec", help="one spec JSON object, or a list of them")
    ap.add_argument("--out-dir", default="resumes")
    ap.add_argument("--check", action="store_true", help="validate only")
    a = ap.parse_args()
    bank = json.load(open(a.bank))
    specs = []
    if a.spec:
        s = json.load(open(a.spec))
        specs = s if isinstance(s, list) else [s]
    errs = validate(bank) + [e for s in specs for e in validate(bank, s)]
    if errs:
        print("INVALID:\n- " + "\n- ".join(errs))
        sys.exit(1)
    if a.check or not specs:
        print("bank OK")
        return
    for r in asyncio.run(build(bank, specs, pathlib.Path(a.out_dir))):
        print(json.dumps(r))
        if not r["one_page"]:
            print("OVER ONE PAGE: drop a bullet or a project and rebuild", file=sys.stderr)


if __name__ == "__main__":
    main()
