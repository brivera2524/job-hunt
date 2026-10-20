#!/usr/bin/env python3
"""Job feed: pulls open roles from public company job boards and filters them
against a search config. No accounts or API keys needed.

Sources (per watchlist entry "ats"):
  greenhouse, lever, ashby, smartrecruiters  -> public JSON boards; applications need no account
  workday                                    -> public career-site JSON; applying needs the user's own account

Commands:
  run     python3 jobfeed.py run --config config.json --seen seen.json --tracker tracker.json --out leads.json
  ingest  python3 jobfeed.py ingest --config config.json --seen seen.json --tracker tracker.json \
              --input connector_leads.json --out leads.json
          (filters and dedupes leads Claude collected from job-board connectors such as Indeed;
           input is a JSON list of {company, title, url, location, description?, pay?, source})
  board   python3 jobfeed.py board <board URL | slug --ats greenhouse> --grep "support engineer"
          (lists one board's open jobs whose titles contain all the words: for matching a job-board
           listing to the employer's own posting)
  alive   python3 jobfeed.py alive --input jobs.json --out alive.json
          (checks whether tracked postings are still open; input is a JSON list of {id, url};
           output adds alive: true | false | null (null = couldn't tell) and why)
  account python3 jobfeed.py account <url> [...]
          (prints the apply route for each URL and which account it needs: key, system, sign-in tip)
  probe   python3 jobfeed.py probe --config config.json slug-or-url [...]
          (finds which ATS a company uses and adds it to the watchlist; accepts company slugs,
           careers-page URLs on the supported ATSs, or Workday URLs like
           https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers)

The script only narrows the field (title, location, seniority, sales words, dedupe).
Judging fit against the candidate's profile is Claude's job.
"""
import argparse, concurrent.futures as cf, datetime as dt, html, json, re, sys, urllib.error, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (job-hunt feed)"}
URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true",
    "lever": "https://api.lever.co/v0/postings/{s}?mode=json",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100",
}
GH_JOB = "https://boards-api.greenhouse.io/v1/boards/{s}/jobs/{id}?pay_transparency=true"
SR_JOB = "https://api.smartrecruiters.com/v1/companies/{s}/postings/{id}"
NO_ACCOUNT = {"greenhouse", "lever", "ashby", "smartrecruiters"}
DEFAULT_WD_TERMS = [""]  # empty search = newest postings; setup replaces this with terms from the user's profile
ROUTE_HOSTS = [
    (r"greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|paylocity\.com|workable\.com|bamboohr\.com|applytojob\.com|breezy\.hr|recruitee\.com|jobs\.gem\.com", "no_account"),
    (r"myworkdayjobs\.com|myworkdaysite\.com|jobs\.apple\.com|icims\.com|taleo\.net|oraclecloud\.com|successfactors|ultipro\.com|ukg\.|dayforcehcm\.com|adp\.com", "needs_account"),
    (r"indeed\.com|linkedin\.com|ziprecruiter\.com|dice\.com|glassdoor\.com", "check"),
]


def route_for_url(url):
    """no_account = Claude can submit; needs_account = user signs in first; check = job-board link, resolve first."""
    for rx, route in ROUTE_HOSTS:
        if re.search(rx, url or "", re.I):
            return route
    return "check"


# Which account an application needs. One key per account the user has to create:
# Workday, iCIMS, UKG, Taleo and the like are one account per company; Apple is one Apple ID.
ACCOUNT_RULES = [
    (r"//([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", "workday:{0}", "Workday",
     "Open a posting, click Apply, then Apply Manually, then Create Account. Each company's Workday is a separate account; use the same email and a password manager."),
    (r"myworkdaysite\.com/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/([^/?#]+)", "workday:{0}", "Workday",
     "Open a posting, click Apply, then Apply Manually, then Create Account. Each company's Workday is a separate account; use the same email and a password manager."),
    (r"jobs\.apple\.com", "apple", "Apple ID",
     "Sign in at jobs.apple.com with your Apple ID. One sign-in covers every Apple job."),
    (r"//([a-z0-9-]+)\.icims\.com", "icims:{0}", "iCIMS",
     "Open a posting, click Apply, and create an account with your email."),
    (r"(?:ultipro|ukg)\.com/([A-Za-z0-9]+)", "ukg:{0}", "UKG",
     "Open a posting, click Apply, and create an account with your email."),
    (r"//([a-z0-9-]+)\.taleo\.net", "taleo:{0}", "Taleo",
     "Open a posting, click Apply, and create a new account."),
    (r"//([a-z0-9-]+)\.[a-z0-9.-]*oraclecloud\.com", "oracle:{0}", "Oracle",
     "Open a posting, click Apply, and enter your email; Oracle sends a one-time code."),
    (r"successfactors\.[a-z]+/.*?company=([A-Za-z0-9_]+)", "sf:{0}", "SuccessFactors",
     "Open a posting, click Apply, and create an account."),
    (r"dayforcehcm\.com/(?:CandidatePortal/)?[a-z]{2}-[A-Z]{2}/([^/?#]+)", "dayforce:{0}", "Dayforce",
     "Open a posting, click Apply, and create an account."),
    (r"adp\.com/.*?[?&]cid=([0-9a-f-]+)", "adp:{0}", "ADP",
     "Open a posting, click Apply, and create an account."),
    (r"myjobs\.adp\.com/([^/?#]+)", "adp:{0}", "ADP",
     "Open a posting, click Apply, and create an account."),
    (r"adp\.com/.*?[?&]c=(\d+)", "adp:{0}", "ADP",
     "Open a posting, click Apply, and create an account."),
    (r"smartrecruiters\.com", "smartrecruiters", "SmartRecruiters",
     "Create one SmartRecruiters account; it works for every company on SmartRecruiters."),
]


def account_for(url):
    """Which sign-in an application needs: {key, system, tip}, or None when no account rule matches."""
    for rx, key, system, tip in ACCOUNT_RULES:
        m = re.search(rx, url or "", re.I)
        if m:
            k = key.format(*[g.lower() for g in m.groups()]) if m.groups() else key
            return {"key": re.sub(r"[^a-z0-9:._-]", "-", k), "system": system, "tip": tip,
                    "multiCompany": key == "smartrecruiters"}
    if route_for_url(url) == "needs_account":
        host = urllib.parse.urlparse(url).netloc.lower()
        return {"key": "site:" + host, "system": "account", "tip": "Open a posting, click Apply, and create an account."}
    return None


def http_status(url, timeout=30):
    """(status code, body text) for a GET; (None, '') when the site couldn't be reached."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


def posting_alive(url, cache):
    """True = still open, False = closed, None = couldn't tell (unsupported site or network trouble)."""
    u = url or ""
    def by_status(api):
        code, _ = http_status(api)
        return (True, "open") if code == 200 else (False, f"HTTP {code}") if code in (404, 410) else (None, f"HTTP {code}")
    m = re.search(r"greenhouse\.io/([^/?#]+)/jobs/(\d{5,})", u)
    if m and m.group(1) != "embed":
        return by_status(GH_JOB.format(s=m.group(1), id=m.group(2)))
    m = re.search(r"jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{36})", u)
    if m:
        return by_status(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}")
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", u)
    if m:
        slug = m.group(1)
        if slug not in cache:
            d = get_json(URLS["ashby"].format(s=slug))
            cache[slug] = None if d is None else {j.get("id") for j in d.get("jobs", [])}
        ids = cache[slug]
        return (None, "board unreachable") if ids is None else ((True, "open") if m.group(2) in ids else (False, "not on the board"))
    m = re.search(r"smartrecruiters\.com/([^/?#]+)/(\d{6,})", u)
    if m:
        return by_status(SR_JOB.format(s=m.group(1), id=m.group(2)))
    m = re.search(r"//([a-z0-9-]+)(\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)(/job/[^?#]+)", u)
    if m:
        return by_status(f"https://{m.group(1)}{m.group(2)}/wday/cxs/{m.group(1)}/{m.group(3)}{m.group(4)}")
    m = re.search(r"jobs\.apple\.com/[a-z-]+/details/(\d+)", u)
    if m:
        code, body = http_status(u)
        if code != 200:
            return None, f"HTTP {code}"
        return (True, "open") if f'jobNumber\\":\\"{m.group(1)}' in body or f'"jobNumber":"{m.group(1)}"' in body else (False, "no longer listed")
    return None, "site not supported"


def alive(args):
    rows = json.load(open(args.input))
    cache, out = {}, []
    def one(r):
        a, why = posting_alive(r.get("url"), cache)
        return dict(r, alive=a, why=why)
    with cf.ThreadPoolExecutor(8) as ex:
        out = list(ex.map(one, rows))
    json.dump(out, open(args.out, "w"), indent=1)
    n = lambda v: sum(1 for r in out if r["alive"] is v)
    print(f"checked {len(out)}: open {n(True)}, closed {n(False)}, couldn't tell {n(None)}")


def account_cmd(args):
    for u in args.urls:
        print(json.dumps({"url": u, "route": route_for_url(u), "account": account_for(u)}))


def get_json(url, timeout=40, data=None):
    try:
        headers = dict(UA)
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def text(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def title_key(company, title):
    t = re.sub(r"\(.*?\)|\[.*?\]|-\s*remote.*$", "", (title or "").lower())
    return re.sub(r"[^a-z0-9]", "", (company or "").lower()) + "|" + re.sub(r"[^a-z0-9]+", " ", t).strip()


def job_key(url):
    """Stable id for a posting URL, so tracker links and feed links compare equal."""
    u = url or ""
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", u, re.I)
    if m:
        return m.group(0).lower()
    m = re.search(r"//([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com/.*?_([A-Z]*-?\d{4,}(?:-\d+)?)", u, re.I)
    if m:
        return f"wd:{m.group(1).lower()}:{m.group(2).lower()}"
    m = re.search(r"smartrecruiters\.com/[^/]+/(\d{6,})", u)
    if m:
        return "sr" + m.group(1)
    m = re.search(r"greenhouse\.io/.*?(?:jobs/|token=)(\d{5,})|[?&]gh_jid=(\d{5,})", u)
    if m:
        return "gh" + (m.group(1) or m.group(2))
    m = re.search(r"indeed\.com/.*?[?&]jk=([0-9a-f]+)", u, re.I)
    if m:
        return "indeed:" + m.group(1).lower()
    return re.sub(r"[?#].*$", "", u).rstrip("/").lower()


# ---------- normalize each source into one shape ----------

def norm_greenhouse(b, d):
    for j in d.get("jobs", []):
        yield dict(company=b["company"], ats="greenhouse", board=b, id=j["id"], title=j["title"],
                   location=(j.get("location") or {}).get("name", ""), url=j["absolute_url"],
                   posted=(j.get("updated_at") or "")[:10], desc=None, pay="", remote_flag=None)


def norm_ashby(b, d):
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in (j.get("secondaryLocations") or [])]
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        loc = "; ".join(x for x in locs if x) + (f" [{country}]" if country else "")
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        # Ashby's isRemote flag is unreliable (true on hybrid roles); workplaceType is not.
        yield dict(company=b["company"], ats="ashby", board=b, id=j.get("id"), title=j["title"], location=loc,
                   url=j["jobUrl"], posted=(j.get("publishedAt") or "")[:10], desc=j.get("descriptionPlain") or "",
                   pay=comp, remote_flag=(j.get("workplaceType") == "Remote"),
                   employment=j.get("employmentType", ""), workplace=j.get("workplaceType", ""))


def norm_lever(b, d):
    for j in d if isinstance(d, list) else []:
        c = j.get("categories") or {}
        locs = c.get("allLocations") or [c.get("location", "")]
        loc = "; ".join(x for x in locs if x) + (f" [{j.get('country')}]" if j.get("country") else "")
        sr = j.get("salaryRange") or {}
        pay = f"${sr['min']:,}–${sr['max']:,} {sr.get('interval', '')}".strip() if sr.get("min") and sr.get("max") else ""
        lists = " ".join(f"{x.get('text', '')}: {text(x.get('content', ''))}" for x in j.get("lists") or [])
        posted = dt.datetime.fromtimestamp(j["createdAt"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d") if j.get("createdAt") else ""
        yield dict(company=b["company"], ats="lever", board=b, id=j["id"], title=j["text"], location=loc,
                   url=j["hostedUrl"], posted=posted, desc=f"{j.get('descriptionPlain', '')} {lists} {j.get('additionalPlain', '')}",
                   pay=pay, remote_flag=(j.get("workplaceType") == "remote"), employment=c.get("commitment", ""),
                   workplace=j.get("workplaceType", ""))


def norm_smartrecruiters(b, d):
    for j in d.get("content", []):
        l = j.get("location") or {}
        loc = l.get("fullLocation") or ", ".join(x for x in [l.get("city"), l.get("region"), l.get("country")] if x)
        if l.get("remote"):
            loc += " (Remote)"
        yield dict(company=(j.get("company") or {}).get("name") or b["company"], ats="smartrecruiters", board=b,
                   id=j["id"], title=j["name"], location=loc + f" [{l.get('country', '')}]",
                   url=f"https://jobs.smartrecruiters.com/{b['slug']}/{j['id']}", posted=(j.get("releasedDate") or "")[:10],
                   desc=None, pay="", remote_flag=bool(l.get("remote")),
                   employment=(j.get("typeOfEmployment") or {}).get("label", ""))


def norm_workday(b, d):
    for j in d.get("jobPostings", []):
        if not j.get("externalPath"):
            continue
        yield dict(company=b["company"], ats="workday", board=b, id=j["externalPath"], title=j.get("title", ""),
                   location=j.get("locationsText", ""), url=f"https://{b['host']}/en-US/{b['site']}{j['externalPath']}",
                   posted=j.get("postedOn", ""), desc=None, pay="", remote_flag=None)


NORM = {"greenhouse": norm_greenhouse, "ashby": norm_ashby, "lever": norm_lever,
        "smartrecruiters": norm_smartrecruiters, "workday": norm_workday}


def wd_api(b):
    tenant = b["host"].split(".")[0]
    return f"https://{b['host']}/wday/cxs/{tenant}/{b['site']}"


def fetch_workday(b, terms, max_pages=5):
    seen, postings = set(), []
    for term in terms:
        for page in range(max_pages):
            d = get_json(wd_api(b) + "/jobs", data={"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": term})
            if not d:
                if page == 0 and not postings and term == terms[0]:
                    return None
                break
            batch = d.get("jobPostings", [])
            for j in batch:
                if j.get("externalPath") and j["externalPath"] not in seen:
                    seen.add(j["externalPath"])
                    postings.append(j)
            if len(batch) < 20:
                break
    return {"jobPostings": postings}


def fetch_sr(slug):
    first = get_json(URLS["smartrecruiters"].format(s=slug))
    if not first or not first.get("totalFound"):
        return None
    content = first["content"]
    for off in range(100, min(first["totalFound"], 1500), 100):
        content += (get_json(URLS["smartrecruiters"].format(s=slug) + f"&offset={off}") or {}).get("content", [])
    return {"content": content}


def fetch_board(args):
    b, wd_terms = args
    b.setdefault("company", b.get("slug") or b.get("host", "").split(".")[0])
    if b["ats"] == "workday":
        d = fetch_workday(b, wd_terms)
    elif b["ats"] == "smartrecruiters":
        d = fetch_sr(b["slug"])
    else:
        d = get_json(URLS[b["ats"]].format(s=b["slug"]))
    if d is None:
        return b, None
    return b, list(NORM[b["ats"]](b, d))


# ---------- filters ----------

def compile_cfg(cfg):
    f = cfg["filters"]
    rx = lambda k: re.compile(f[k], re.I) if f.get(k) else None
    return dict(include=rx("title_include"), exclude=rx("title_exclude"), local=rx("local_places"),
                nonus=rx("non_us_places"), us=rx("us_words"), desc_flags=rx("description_flags"),
                allow_remote=f.get("allow_remote_us", True), allow_local=f.get("allow_local", True),
                local_label=f.get("local_label", "local"))


def classify_location(j, c):
    loc, title = j.get("location") or "", j.get("title") or ""
    workplace = j.get("workplace") or ""
    blob = f"{loc} {workplace}"
    if c["nonus"] and c["nonus"].search(title):
        return None
    m = re.search(r"\[([A-Za-z .]+)\]\s*$", loc)
    if m and m.group(1).strip() and not re.fullmatch(r"(?i)us|usa|u\.s\.a?\.?|united states( of america)?", m.group(1).strip()):
        return None
    if c["allow_local"] and c["local"] and c["local"].search(loc):
        return c["local_label"]
    is_remote = bool(j.get("remote_flag")) or re.search(r"remote|anywhere", blob, re.I) or workplace.strip().lower() == "distributed"
    if c["allow_remote"] and is_remote:
        if (c["us"] and c["us"].search(blob)) or not (c["nonus"] and c["nonus"].search(loc)):
            return "remote"
    return None


def wd_detail(j):
    b = j["board"]
    d = get_json(wd_api(b) + j["id"]) or {}
    info = d.get("jobPostingInfo") or {}
    j["desc"] = text(info.get("jobDescription", ""))
    locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
    country = (info.get("country") or {}).get("descriptor", "")
    j["location"] = "; ".join(x for x in locs if x) + (f" [{country}]" if country else "")
    if (info.get("remoteType") or "").lower() == "remote":
        j["remote_flag"] = True
    j["employment"] = info.get("timeType", "")
    if info.get("startDate"):
        j["posted"] = info["startDate"]
    return j


YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?years?", re.I)
MONEY = re.compile(r"\$\s?\d{2,3}(?:,\d{3}|k|K)(?:\s*(?:-|–|to)\s*\$?\s?\d{2,3}(?:,\d{3}|k|K))?")


def enrich(j):
    if j.get("ats") == "greenhouse" and j.get("desc") is None:
        d = get_json(GH_JOB.format(s=j["board"]["slug"], id=j["id"])) or {}
        j["desc"] = text(d.get("content", ""))
        pr = d.get("pay_input_ranges") or []
        if pr:
            j["pay"] = f"${pr[0]['min_cents'] // 100:,}–${pr[0]['max_cents'] // 100:,}"
    if j.get("ats") == "smartrecruiters" and j.get("desc") is None:
        d = get_json(SR_JOB.format(s=j["board"]["slug"], id=j["id"])) or {}
        secs = ((d.get("jobAd") or {}).get("sections") or {})
        j["desc"] = " ".join(text((v or {}).get("text", "")) for v in secs.values())
    if j.get("ats") == "workday" and j.get("desc") is None:
        wd_detail(j)
    j["desc"] = text(j.get("desc") or "")
    if not j.get("pay"):
        m = MONEY.search(j["desc"])
        j["pay"] = m.group(0) if m else ""
    # first plausible experience ask; skips company-history boilerplate like "25+ years in business"
    j["years"] = ""
    for m in YEARS.finditer(j["desc"]):
        if int(m.group(1)) < 15:
            j["years"] = m.group(1) + ("–" + m.group(2) if m.group(2) else "+")
            break
    return j


def load_state(args):
    seen = {}
    try:
        seen = json.load(open(args.seen))
    except Exception:
        pass
    tracked, tracked_titles = set(), set()
    if args.tracker:
        for r in json.load(open(args.tracker)):
            tracked.add(job_key(r.get("url", "")))
            tracked_titles.add(title_key(r.get("company", ""), r.get("title", "")))
    return seen, tracked, tracked_titles


def finish(cfg, c, args, cands, seen, tracked, tracked_titles, extra_summary):
    """Dedupe, enrich, drop too-senior, write leads + seen. Shared by run and ingest."""
    today = dt.date.today().isoformat()
    new, by_title = [], {}
    for j in cands:
        tk = title_key(j["company"], j["title"])
        if j["key"] in tracked or j["key"] in seen or tk in tracked_titles:
            continue
        if tk in by_title:  # same role posted in several places: keep one, note the rest
            by_title[tk]["other_locations"].append(j.get("location", ""))
            seen[j["key"]] = today
            continue
        j["other_locations"] = []
        by_title[tk] = j
        new.append(j)
    with cf.ThreadPoolExecutor(12) as ex:
        new = list(ex.map(enrich, new))
    out, too_senior, dropped_loc = [], 0, 0
    f = cfg["filters"]
    maxy, maxpay = f.get("max_years_required"), f.get("max_pay_floor")
    for j in new:
        seen[j["key"]] = today
        if j.get("ats") == "workday":  # full location is only known after the detail fetch
            region = classify_location(j, c)
            if not region:
                dropped_loc += 1
                continue
            j["region"] = region
        y = int(re.match(r"\d+", j["years"]).group(0)) if j["years"] else None
        p = re.search(r"\$\s?(\d{2,3})(?:,(\d{3})|(\.\d)?[kK])", j.get("pay") or "")
        pmin = int(p.group(1)) * 1000 if p else None
        if (maxy and y and 0 < y < 25 and y > maxy) or (maxpay and pmin and pmin > maxpay):
            too_senior += 1
            continue
        flags = sorted(set(m.group(0).lower() for m in c["desc_flags"].finditer(j["desc"]))) if c["desc_flags"] else []
        ats = j.get("ats", "")
        out.append(dict(key=j["key"], company=j["company"], title=j["title"], location=j.get("location", ""),
                        region=j["region"], other_locations=j["other_locations"], pay=j.get("pay", ""), years=j["years"],
                        posted=j.get("posted", ""), url=j["url"], ats=ats, source=j.get("source", ats),
                        apply_route=route_for_url(j["url"]),
                        flags=flags, description=j["desc"][: args.desc_chars]))
    out.sort(key=lambda r: (r["region"] != c["local_label"], r["company"].lower(), r["title"]))
    prev = []
    if getattr(args, "append", False):
        try:
            prev = json.load(open(args.out))
        except Exception:
            prev = []
    json.dump(prev + out, open(args.out, "w"), indent=1, ensure_ascii=False)
    json.dump(seen, open(args.seen, "w"), indent=0, sort_keys=True)
    summary = dict(date=today, matched_filters=len(cands), already_tracked_or_seen=len(cands) - len(new),
                   dropped_as_too_senior=too_senior, dropped_location_after_detail=dropped_loc, new_leads=len(out))
    summary.update(extra_summary)
    print(json.dumps(summary, indent=1))


def passes_title(j, c):
    return c["include"].search(j["title"] or "") and not (c["exclude"] and c["exclude"].search(j["title"] or ""))


def run(args):
    cfg = json.load(open(args.config))
    c = compile_cfg(cfg)
    seen, tracked, tracked_titles = load_state(args)
    wd_terms = cfg.get("workday_search_terms") or DEFAULT_WD_TERMS
    boards = cfg["watchlist"]
    dead, total, cands = [], 0, []
    with cf.ThreadPoolExecutor(16) as ex:
        for b, jobs in ex.map(fetch_board, [(b, wd_terms) for b in boards]):
            if jobs is None:
                dead.append(f"{b['ats']}:{b.get('slug') or b.get('host')}")
                continue
            total += len(jobs)
            for j in jobs:
                if not passes_title(j, c):
                    continue
                if j["ats"] == "workday" and re.search(r"\d+ Locations", j["location"] or ""):
                    region = "pending"  # resolved after the detail fetch
                else:
                    region = classify_location(j, c)
                if not region:
                    continue
                if j.get("employment") and re.search(r"intern|contract|part", j["employment"], re.I) and not args.include_contract:
                    continue
                j["region"], j["key"] = region, job_key(j["url"])
                cands.append(j)
    for j in cands:
        if j["region"] == "pending":
            wd_detail(j)
            j["region"] = classify_location(j, c) or "pending"
    cands = [j for j in cands if j["region"] != "pending"]
    finish(cfg, c, args, cands, seen, tracked, tracked_titles,
           dict(boards=len(boards), boards_unreachable=len(dead), postings_scanned=total, unreachable=dead))


def ingest(args):
    cfg = json.load(open(args.config))
    c = compile_cfg(cfg)
    seen, tracked, tracked_titles = load_state(args)
    rows = json.load(open(args.input))
    cands, skipped = [], 0
    for r in rows:
        j = dict(company=r.get("company", ""), title=r.get("title", ""), location=r.get("location", ""),
                 url=r.get("url", ""), desc=r.get("description") or "", pay=r.get("pay", ""), posted=r.get("posted", ""),
                 remote_flag=bool(r.get("remote")), ats=r.get("ats", ""), source=r.get("source", "connector"))
        if not j["url"] or not passes_title(j, c):
            skipped += 1
            continue
        region = classify_location(j, c)
        if not region:
            skipped += 1
            continue
        j["region"], j["key"] = region, job_key(j["url"])
        cands.append(j)
    args.append = True
    finish(cfg, c, args, cands, seen, tracked, tracked_titles, dict(input_rows=len(rows), failed_filters=skipped))


def probe(args):
    cfg = json.load(open(args.config))
    have = {(b["ats"], b.get("slug") or b.get("host")) for b in cfg["watchlist"]}
    added = []

    def try_one(s):
        m = re.match(r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)", s)
        if m:
            b = {"ats": "workday", "host": m.group(1), "site": m.group(2), "company": m.group(1).split(".")[0]}
            d = get_json(wd_api(b) + "/jobs", data={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}, timeout=20)
            return s, ([(b, d.get("total", 0))] if d else [])
        m = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([^/?&#]+)|jobs\.lever\.co/([^/?#]+)|jobs\.ashbyhq\.com/([^/?#]+)|smartrecruiters\.com/([^/?#]+)", s)
        slug = next((g for g in m.groups() if g), None) if m else s
        only = None
        if m:  # the URL names its ATS: check only that one, so unrelated companies sharing the slug aren't added
            only = ["greenhouse", "lever", "ashby", "smartrecruiters"][[i for i, g in enumerate(m.groups()) if g][0]]
        hits = []
        for ats in ([only] if only else URLS):
            d = get_json(URLS[ats].format(s=slug), timeout=20)
            n = d.get("totalFound", 0) if isinstance(d, dict) and "totalFound" in d else (
                len(d.get("jobs", [])) if isinstance(d, dict) else (len(d) if isinstance(d, list) else 0))
            if d is not None and n > 0:
                hits.append(({"ats": ats, "slug": slug, "company": slug}, n))
        return s, hits

    with cf.ThreadPoolExecutor(12) as ex:
        for s, hits in ex.map(try_one, args.targets):
            if not hits:
                print(f"{s}: not found")
            for b, n in hits:
                ident = (b["ats"], b.get("slug") or b.get("host"))
                print(f"{s}: {b['ats']} ({n} jobs)")
                if ident not in have:
                    if args.company:
                        b["company"] = args.company
                    cfg["watchlist"].append(b)
                    have.add(ident)
                    added.append(ident)
    cfg["watchlist"].sort(key=lambda b: ((b.get("slug") or b.get("host") or "").lower(), b["ats"]))
    json.dump(cfg, open(args.config, "w"), indent=1)
    print(f"added {len(added)} boards; watchlist now {len(cfg['watchlist'])}")


def board(args):
    """List a board's open jobs, optionally filtered by title words, to match a job-board listing to the employer's posting."""
    s = args.target
    m = re.match(r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)", s)
    if m:
        b = {"ats": "workday", "host": m.group(1), "site": m.group(2), "company": m.group(1).split(".")[0]}
        terms = [args.grep] if args.grep else [""]
    else:
        ats, slug = (args.ats, s) if args.ats else (None, s)
        mm = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?&#]+)|jobs\.lever\.co/([^/?#]+)|jobs\.ashbyhq\.com/([^/?#]+)|smartrecruiters\.com/([^/?#]+)", s)
        if mm:
            idx = [i for i, g in enumerate(mm.groups()) if g][0]
            ats, slug = ["greenhouse", "lever", "ashby", "smartrecruiters"][idx], mm.groups()[idx]
        if not ats:
            sys.exit("give --ats or a board URL")
        b = {"ats": ats, "slug": slug, "company": slug}
        terms = [""]
    b, jobs = fetch_board((b, terms))
    if jobs is None:
        sys.exit("board not reachable")
    words = [w.lower() for w in (args.grep or "").split()]
    for j in jobs:
        if all(w in j["title"].lower() for w in words):
            print(f"{j['title']} | {j['location']} | {j['url']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "ingest"):
        r = sp.add_parser(name)
        r.add_argument("--config", default="config.json")
        r.add_argument("--seen", default="seen.json")
        r.add_argument("--tracker", help="JSON list of {company, title, url} already in the tracker")
        r.add_argument("--out", default="leads.json")
        r.add_argument("--desc-chars", type=int, default=4000)
        r.add_argument("--include-contract", action="store_true")
        if name == "ingest":
            r.add_argument("--input", required=True, help="JSON list of leads from job-board connectors")
    bd = sp.add_parser("board")
    bd.add_argument("target", help="board URL, or a slug together with --ats")
    bd.add_argument("--ats", choices=["greenhouse", "lever", "ashby", "smartrecruiters"])
    bd.add_argument("--grep", help="words that must all appear in the title")
    al = sp.add_parser("alive")
    al.add_argument("--input", required=True, help="JSON list of {id, url}")
    al.add_argument("--out", default="alive.json")
    ac = sp.add_parser("account")
    ac.add_argument("urls", nargs="+")
    q = sp.add_parser("probe")
    q.add_argument("--config", default="config.json")
    q.add_argument("--company", help="display name to store for a single target")
    q.add_argument("targets", nargs="+")
    a = p.parse_args()
    {"run": run, "ingest": ingest, "probe": probe, "board": board, "alive": alive, "account": account_cmd}[a.cmd](a)
