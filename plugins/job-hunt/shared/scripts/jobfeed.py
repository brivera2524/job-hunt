#!/usr/bin/env python3
"""Job feed: pulls open roles from public company job boards and filters them
against a search config. No accounts or API keys needed.

Sources (per watchlist entry "ats"):
  greenhouse, lever, ashby, smartrecruiters,
  workable, recruitee, bamboohr, breezy,
  rippling, gem, teamtailor, pinpoint,
  personio                                   -> public company boards; applications usually need no account
  Config "bulk_lists" also scans public lists of thousands more boards (github.com/kalil0321/ats-scrapers).
  workday                                    -> public career-site JSON; applying needs the user's own account

Aggregators (config "aggregators"; see AGGREGATORS below). These search across many employers at once:
  keyless:  smartrecruiters (search across every company), themuse, remotive, remoteok, himalayas, jobicy,
            weworkremotely, hn (Hacker News "Who is hiring")
  free key: adzuna, usajobs, jooble     paid / free tier: serpapi (Google Jobs), jsearch (RapidAPI, Google Jobs)
  Listings that link to a company board on a supported ATS add that board to the watchlist
  automatically, so each run widens the next one.

Commands:
  run     python3 jobfeed.py run --config config.json --seen seen.json --tracker tracker.json --out leads.json
          [--no-aggregators] [--only-aggregators] [--no-grow] [--no-bulk] [--no-resolve]
  resolve python3 jobfeed.py resolve --config config.json --input connector_leads.json
          (finds each job-board listing on the employer's own board, rewrites url, and adds found boards
           to the watchlist; run and ingest do this automatically unless --no-resolve)
  peek    python3 jobfeed.py peek leads.json
          (one line per lead: index, company, title, location, region, pay, years, source, route, flags)
  sources python3 jobfeed.py sources --config config.json
          (lists every aggregator, whether it's on, and what it still needs, such as an API key)
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
          (finds which ATS a company uses and adds it to the watchlist; accepts company slugs (tried on
           every supported ATS), careers-page or posting URLs on the supported ATSs, or Workday URLs like
           https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers)

The script only narrows the field (title, location, seniority, sales words, dedupe).
Judging fit against the candidate's profile is Claude's job.
"""
import argparse, concurrent.futures as cf, datetime as dt, html, json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (job-hunt feed)"}
URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true",
    "lever": "https://api.lever.co/v0/postings/{s}?mode=json",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{s}",
    "recruitee": "https://{s}.recruitee.com/api/offers/",
    "bamboohr": "https://{s}.bamboohr.com/careers/list",
    "breezy": "https://{s}.breezy.hr/json",
    "rippling": "https://api.rippling.com/platform/api/ats/v1/board/{s}/jobs",
    "gem": "https://api.gem.com/job_board/v0/{s}/job_posts/",
    "personio": "https://{s}.jobs.personio.de/xml",
    "teamtailor": "https://{s}.teamtailor.com/jobs.json",
    "pinpoint": "https://{s}.pinpointhq.com/postings.json",
}
# Big public lists of company boards per ATS (MIT-licensed, community-maintained, refreshed often):
# github.com/kalil0321/ats-scrapers. Config "bulk_lists" names which ATSs to scan in full on every run.
BULK_LIST_URL = "https://raw.githubusercontent.com/kalil0321/ats-scrapers/main/ats-companies/{ats}.csv"
BULK_OK = {"greenhouse", "lever", "ashby", "recruitee", "teamtailor", "pinpoint", "personio"}  # smartrecruiters: use the search aggregator
# Company-board ATSs in the order probe tries them. Workable rate-limits hard, so it goes last.
PROBE_ORDER = ["greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "bamboohr", "breezy", "rippling",
               "gem", "teamtailor", "pinpoint", "personio", "workable"]
GH_JOB = "https://boards-api.greenhouse.io/v1/boards/{s}/jobs/{id}?pay_transparency=true"
SR_JOB = "https://api.smartrecruiters.com/v1/companies/{s}/postings/{id}"
BAMBOO_JOB = "https://{s}.bamboohr.com/careers/{id}/detail"
RIPPLING_JOB = "https://api.rippling.com/platform/api/ats/v1/board/{s}/jobs/{id}"
NO_ACCOUNT = {"greenhouse", "lever", "ashby", "smartrecruiters", "workable", "recruitee", "bamboohr", "breezy",
              "rippling", "gem", "personio", "teamtailor", "pinpoint"}
DEFAULT_WD_TERMS = [""]  # empty search = newest postings; setup replaces this with terms from the user's profile
# Sites whose own apply flow must never be automated (rules.md section 3). A job that can only be applied
# for there becomes an "apply yourself" job: Claude prepares the kit, the user clicks submit.
JOB_BOARD_HOSTS = (r"indeed\.com|linkedin\.com|ziprecruiter\.com|dice\.com|glassdoor\.com|wellfound\.com|angel\.co|"
                   r"builtin[a-z]*\.com|simplyhired\.com|monster\.com|careerbuilder\.com|joinhandshake\.com|"
                   r"welcometothejungle\.com|otta\.com|hired\.com|google\.com|remotive\.com|remoteok\.(?:com|io)|"
                   r"himalayas\.app|jobicy\.com|weworkremotely\.com|ycombinator\.com|workatastartup\.com|"
                   r"adzuna\.[a-z.]+|jooble\.org|talent\.com|snagajob\.com|flexjobs\.com")
ROUTE_HOSTS = [
    (r"greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|paylocity\.com|workable\.com|bamboohr\.com|applytojob\.com|breezy\.hr|recruitee\.com|jobs\.gem\.com|ats\.rippling\.com|jobs\.personio\.[a-z]+|pinpointhq\.com|teamtailor\.com", "no_account"),
    (r"myworkdayjobs\.com|myworkdaysite\.com|jobs\.apple\.com|icims\.com|taleo\.net|oraclecloud\.com|successfactors|ultipro\.com|ukg\.|dayforcehcm\.com|adp\.com|usajobs\.gov", "needs_account"),
    (JOB_BOARD_HOSTS, "check"),
]
# A company board named by a URL: (regex, ats). The first group is the board slug.
BOARD_URL_RULES = [
    (r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_app\?for=)?([^/?&#]+)", "greenhouse"),
    (r"boards-api\.greenhouse\.io/v1/boards/([^/?&#]+)", "greenhouse"),
    (r"jobs\.lever\.co/([^/?#]+)", "lever"),
    (r"jobs\.ashbyhq\.com/([^/?#]+)", "ashby"),
    (r"jobs\.smartrecruiters\.com/([^/?#]+)", "smartrecruiters"),
    (r"careers\.smartrecruiters\.com/([^/?#]+)", "smartrecruiters"),
    (r"apply\.workable\.com/([^/?#]+)", "workable"),
    (r"//([a-z0-9-]+)\.recruitee\.com", "recruitee"),
    (r"//([a-z0-9-]+)\.bamboohr\.com", "bamboohr"),
    (r"//([a-z0-9-]+)\.breezy\.hr", "breezy"),
    (r"ats\.rippling\.com/([^/?#]+)", "rippling"),
    (r"jobs\.gem\.com/([^/?#]+)", "gem"),
    (r"//([a-z0-9-]+)\.jobs\.personio\.[a-z]+", "personio"),
    (r"//([a-z0-9-]+)\.teamtailor\.com", "teamtailor"),
    (r"//([a-z0-9-]+)\.pinpointhq\.com", "pinpoint"),
]
NOT_SLUGS = {"j", "embed", "api", "v1", "jobs", "careers", "www", "app", "en", "en-us", "search", "apply", "job"}


def board_from_url(url):
    """The company board a posting or careers URL belongs to, as a watchlist entry, or None."""
    u = url or ""
    m = re.match(r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)", u)
    if m and m.group(2).lower() not in ("wday", "job"):
        return {"ats": "workday", "host": m.group(1), "site": m.group(2), "company": m.group(1).split(".")[0]}
    for rx, ats in BOARD_URL_RULES:
        m = re.search(rx, u, re.I)
        if m and m.group(1).lower() not in NOT_SLUGS:
            slug = m.group(1) if ats == "smartrecruiters" else m.group(1).lower()
            return {"ats": ats, "slug": slug, "company": slug}
    return None


def route_for_url(url):
    """no_account = Claude can submit; needs_account = user signs in first; check = job-board link, resolve first."""
    if re.search(r"[?&](gh_jid|ashby_jid|lever-origin|lever_jid)=", url or "", re.I):
        return "no_account"  # an ATS posting embedded on the company's own site
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
    (r"usajobs\.gov", "usajobs", "USAJOBS",
     "Sign in at usajobs.gov with Login.gov and build your USAJOBS profile and resume once. One account covers every federal job."),
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
                    "multiCompany": key in ("smartrecruiters", "usajobs")}
    if route_for_url(url) == "needs_account":
        host = urllib.parse.urlparse(url).netloc.lower()
        return {"key": "site:" + host, "system": "account", "tip": "Open a posting, click Apply, and create an account."}
    return None


def http_status(url, timeout=30, limit=4_000_000):
    """(status code, body text) for a GET; (None, '') when the site couldn't be reached."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.status, r.read(limit).decode("utf-8", "replace")
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
    if route_for_url(u) == "no_account":  # other company boards: a missing page means closed; a live page proves little
        code, _ = http_status(u, 20, 50_000)
        if code in (404, 410):
            return False, f"HTTP {code}"
        return None, f"HTTP {code}" if code else "unreachable"
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


def get_json(url, timeout=40, data=None, headers=None):
    try:
        headers = dict(UA, **(headers or {}))
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
    m = re.search(r"indeed\.com/.*?[?&](?:jk|vjk)=([0-9a-f]+)", u, re.I)
    if m:
        return "indeed:" + m.group(1).lower()
    m = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*?-)?(\d{6,})|linkedin\.com/jobs/.*?[?&]currentJobId=(\d{6,})", u, re.I)
    if m:
        return "li:" + (m.group(1) or m.group(2))
    m = re.search(r"glassdoor\.[a-z.]+/.*?(?:jobListingId|jl)=(\d+)", u, re.I)
    if m:
        return "gd:" + m.group(1)
    m = re.search(r"workable\.com/(?:[^/?#]+/)?j/([0-9A-F]{6,})", u, re.I)
    if m:
        return "wk:" + m.group(1).upper()
    m = re.search(r"news\.ycombinator\.com/item\?id=(\d+)", u)
    if m:
        return "hn:" + m.group(1)
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


def _loc(*parts):
    return ", ".join(p for p in parts if p and str(p).strip())


def norm_workable(b, d):
    for j in d.get("jobs", []) if isinstance(d, dict) else []:
        locs = [x for x in (j.get("locations") or []) if not x.get("hidden")]
        loc = "; ".join(_loc(x.get("city"), x.get("region"), x.get("country")) for x in locs) or _loc(j.get("city"), j.get("state"), j.get("country"))
        cc = (locs[0].get("countryCode") if locs else "") or ""
        if j.get("telecommuting"):
            loc += " (Remote)"
        yield dict(company=d.get("name") or b["company"], ats="workable", board=b, id=j.get("shortcode"), title=j.get("title", ""),
                   location=loc + (f" [{cc}]" if cc else ""), url=j.get("url") or j.get("shortlink", ""),
                   posted=(j.get("published_on") or j.get("created_at") or "")[:10], desc=None, pay="",
                   remote_flag=bool(j.get("telecommuting")), employment=j.get("employment_type", ""))


def norm_recruitee(b, d):
    for j in (d or {}).get("offers", []):
        if j.get("status") not in (None, "published"):
            continue
        sal = j.get("salary") or {}
        pay = f"{sal.get('currency') or ''} {sal['min']}–{sal['max']} {sal.get('period') or ''}".strip() if sal.get("min") and sal.get("max") else ""
        loc = j.get("location") or _loc(j.get("city"), j.get("state_name"), j.get("country"))
        if j.get("remote"):
            loc += " (Remote)"
        yield dict(company=j.get("company_name") or b["company"], ats="recruitee", board=b, id=j.get("id"), title=j.get("title", ""),
                   location=loc + (f" [{j['country_code']}]" if j.get("country_code") else ""),
                   url=j.get("careers_url") or j.get("careers_apply_url", ""), posted=(j.get("published_at") or "")[:10],
                   desc=f"{j.get('description', '')} {j.get('requirements', '')}", pay=pay, remote_flag=bool(j.get("remote")),
                   employment=j.get("employment_type_code", ""), workplace="hybrid" if j.get("hybrid") else "")


def norm_bamboohr(b, d):
    for j in (d or {}).get("result", []) if isinstance(d, dict) else []:
        l = j.get("location") or {}
        al = j.get("atsLocation") or {}
        loc = _loc(l.get("city") or al.get("city"), l.get("state") or al.get("state") or al.get("province"), al.get("country"))
        remote = bool(j.get("isRemote")) or (j.get("locationType") == "1")
        if remote:
            loc += " (Remote)"
        yield dict(company=b["company"], ats="bamboohr", board=b, id=j.get("id"), title=j.get("jobOpeningName", ""),
                   location=loc, url=f"https://{b['slug']}.bamboohr.com/careers/{j.get('id')}", posted="", desc=None, pay="",
                   remote_flag=remote, employment=j.get("employmentStatusLabel", ""))


def norm_breezy(b, d):
    for j in d if isinstance(d, list) else []:
        l = j.get("location") or {}
        country = (l.get("country") or {}).get("id") if isinstance(l.get("country"), dict) else ""
        loc = l.get("name") or _loc(l.get("city"), (l.get("state") or {}).get("name") if isinstance(l.get("state"), dict) else "")
        if l.get("is_remote"):
            loc += " (Remote)"
        yield dict(company=(j.get("company") or {}).get("name") or b["company"], ats="breezy", board=b, id=j.get("id"),
                   title=j.get("name", ""), location=loc + (f" [{country}]" if country else ""), url=j.get("url", ""),
                   posted=(j.get("published_date") or "")[:10], desc=None, pay=str(j.get("salary") or ""),
                   remote_flag=bool(l.get("is_remote")), employment=(j.get("type") or {}).get("name", ""))


def norm_rippling(b, d):
    for j in d if isinstance(d, list) else []:
        loc = (j.get("workLocation") or {}).get("label", "")
        yield dict(company=b["company"], ats="rippling", board=b, id=j.get("uuid"), title=(j.get("name") or "").strip(),
                   location=loc, url=j.get("url", ""), posted="", desc=None, pay="", remote_flag=None)


def norm_gem(b, d):
    for j in d if isinstance(d, list) else []:
        lt = (j.get("location_type") or "").lower()
        yield dict(company=b["company"], ats="gem", board=b, id=j.get("id"), title=j.get("title", ""),
                   location=(j.get("location") or {}).get("name", "") + (" (Remote)" if lt == "remote" else ""),
                   url=j.get("absolute_url", ""), posted=(j.get("first_published_at") or "")[:10],
                   desc=j.get("content_plain") or j.get("content") or "", pay="", remote_flag=lt == "remote",
                   employment=j.get("employment_type", ""), workplace=lt)


def norm_personio(b, d):
    for p in re.findall(r"<position>(.*?)</position>", d or "", re.S):
        tag = lambda t: html.unescape((re.search(rf"<{t}>(.*?)</{t}>", p, re.S) or [None, ""])[1]).strip()
        pid = tag("id")
        desc = " ".join(re.findall(r"<value>(.*?)</value>", p, re.S))
        yield dict(company=tag("subcompany") or b["company"], ats="personio", board=b, id=pid, title=tag("name"),
                   location=tag("office"), url=f"https://{b['slug']}.jobs.personio.de/job/{pid}",
                   posted=tag("createdAt")[:10], desc=desc, pay="", remote_flag=None,
                   employment=f"{tag('employmentType')} {tag('schedule')}".strip())


def norm_teamtailor(b, d):
    for j in (d or {}).get("items", []) if isinstance(d, dict) else []:
        jp = j.get("_jobposting") or {}
        locs = jp.get("jobLocation") or []
        locs = locs if isinstance(locs, list) else [locs]
        parts, cc = [], ""
        for l in locs:
            a = (l or {}).get("address") or {}
            parts.append(_loc(a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry")))
            cc = cc or a.get("addressCountry") or ""
        remote = jp.get("jobLocationType") == "TELECOMMUTE"
        loc = "; ".join(p for p in parts if p) + (" (Remote)" if remote else "")
        et = jp.get("employmentType") or ""
        yield dict(company=((jp.get("hiringOrganization") or {}).get("name")) or b["company"], ats="teamtailor", board=b,
                   id=j.get("id"), title=j.get("title", ""), location=loc + (f" [{cc}]" if len(cc) == 2 else ""),
                   url=j.get("url", ""), posted=(j.get("date_published") or "")[:10], desc=j.get("content_html") or "",
                   pay="", remote_flag=remote, employment=" ".join(et) if isinstance(et, list) else str(et))


def norm_pinpoint(b, d):
    for j in (d or {}).get("data", []) if isinstance(d, dict) else []:
        l = ((j.get("job") or {}).get("location") or {}) if isinstance(j.get("job"), dict) else {}
        loc = _loc(l.get("city"), l.get("province")) or l.get("name", "")
        wt = (j.get("workplace_type") or "").lower()
        pay = money(j.get("compensation_minimum"), j.get("compensation_maximum"), "", j.get("compensation_frequency") or "") if j.get("compensation_visible") else ""
        yield dict(company=b["company"], ats="pinpoint", board=b, id=j.get("id"), title=j.get("title", ""),
                   location=loc + (" (Remote)" if wt == "remote" else ""), url=j.get("url", ""), posted="",
                   desc=" ".join(str(j.get(k) or "") for k in ("description", "key_responsibilities", "skills_knowledge_expertise")),
                   pay=pay, remote_flag=wt == "remote", employment=j.get("employment_type_text", ""), workplace=wt)


NORM = {"greenhouse": norm_greenhouse, "teamtailor": norm_teamtailor, "pinpoint": norm_pinpoint, "ashby": norm_ashby, "lever": norm_lever,
        "smartrecruiters": norm_smartrecruiters, "workday": norm_workday, "workable": norm_workable,
        "recruitee": norm_recruitee, "bamboohr": norm_bamboohr, "breezy": norm_breezy, "rippling": norm_rippling,
        "gem": norm_gem, "personio": norm_personio}


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


_WORKABLE_LOCK = threading.Lock()
_WORKABLE_LAST = [0.0]


def fetch_raw(ats, slug, timeout=40):
    """The board's raw response (parsed JSON, or text for XML boards), or None when unreachable."""
    url = URLS[ats].format(s=slug)
    if ats == "personio":
        code, body = http_status(url, timeout)
        return body if code == 200 and "<workzag-jobs" in body else None
    if ats == "workable":  # Cloudflare blocks bursts (error 1015): one request at a time, spaced out
        with _WORKABLE_LOCK:
            wait = 1.5 - (time.time() - _WORKABLE_LAST[0])
            if wait > 0:
                time.sleep(wait)
            d = get_json(url, timeout)
            _WORKABLE_LAST[0] = time.time()
        return d
    return get_json(url, timeout)


def fetch_board(args):
    b, wd_terms = args
    b.setdefault("company", b.get("slug") or b.get("host", "").split(".")[0])
    if b["ats"] == "workday":
        d = fetch_workday(b, wd_terms)
    elif b["ats"] == "smartrecruiters":
        d = fetch_sr(b["slug"])
    elif b["ats"] in URLS:
        d = fetch_raw(b["ats"], b["slug"])
    else:
        return b, None
    if d is None:
        return b, None
    try:
        return b, list(NORM[b["ats"]](b, d))
    except Exception:  # an unexpected response shape counts as unreachable rather than stopping the run
        return b, None


# ---------- aggregators: one search across many employers ----------
# Each returns jobs in the same shape as the boards (ats = the aggregator's name). Their own terms ask that the
# listing link and the source name be kept, so every job keeps `listing_url` and `source`.

def best_url(urls):
    """Of several links to one job, prefer the employer's own posting (an ATS), then any non-job-board link."""
    urls = [u for u in urls if u]
    for want in ("no_account", "needs_account"):
        for u in urls:
            if route_for_url(u) == want:
                return u
    for u in urls:
        if not re.search(JOB_BOARD_HOSTS, u, re.I):
            return u
    return urls[0] if urls else ""


def agg_job(source, company, title, location, listing_url, employer_urls=(), desc="", pay="", posted="", remote=None,
            employment=""):
    url = best_url(list(employer_urls) + [listing_url])
    return dict(company=(company or "").strip(), ats=source, source=source, board=None, id=listing_url, title=(title or "").strip(),
                location=location or "", url=url, listing_url=listing_url, posted=(posted or "")[:10], desc=text(desc),
                pay=pay or "", remote_flag=remote, employment=employment or "")


ATS_LINK = re.compile(r"https?://[^\s\"'<>)]+", re.I)


def ats_links(s):
    return [u.rstrip(".,;") for u in ATS_LINK.findall(html.unescape(s or "")) if route_for_url(u) in ("no_account", "needs_account")]


def money(lo, hi, cur="$", per=""):
    try:
        lo, hi = int(float(lo)), int(float(hi))
    except (TypeError, ValueError):
        return ""
    return f"{cur}{lo:,}–{cur}{hi:,}{' ' + per if per else ''}" if lo and hi else ""


def agg_remotive(cfg, opts, terms):
    # Remotive allows about 4 calls a day: one call per run, filtered locally.
    d = get_json("https://remotive.com/api/remote-jobs?category=" + urllib.parse.quote(opts.get("category", "software-dev"))) or {}
    out = []
    for j in d.get("jobs", []):
        if re.search(r"contract|part|freelance|intern", j.get("job_type") or "", re.I):
            continue
        out.append(agg_job("remotive", j.get("company_name"), j.get("title"), f"Remote ({j.get('candidate_required_location') or 'anywhere'})",
                           j.get("url"), ats_links(j.get("description")), j.get("description"), j.get("salary"),
                           j.get("publication_date"), True, j.get("job_type")))
    return out


def agg_themuse(cfg, opts, terms):
    """The Muse: large US index with an experience-level filter; searched by location, filtered by title locally."""
    metro = (cfg.get("location") or {}).get("metro", "")
    places = ([metro] if metro and cfg["filters"].get("allow_local", True) else []) + \
             (["Flexible / Remote"] if cfg["filters"].get("allow_remote_us", True) else [])
    levels = opts.get("levels", ["Entry Level", "Mid Level"])
    out = []
    for place in places:
        for page in range(opts.get("pages", 5)):
            q = [("page", page), ("descending", "true"), ("location", place)] + [("level", l) for l in levels] + \
                [("category", c) for c in opts.get("categories", [])]
            d = get_json("https://www.themuse.com/api/public/jobs?" + urllib.parse.urlencode(q)) or {}
            for j in d.get("results", []):
                locs = "; ".join(x.get("name", "") for x in j.get("locations") or [])
                remote = "remote" in locs.lower() or "flexible" in locs.lower()
                out.append(agg_job("themuse", (j.get("company") or {}).get("name"), j.get("name"), locs + (" (Remote)" if remote else ""),
                                   (j.get("refs") or {}).get("landing_page"), [], j.get("contents"), "", j.get("publication_date"),
                                   remote or None))
            if page + 1 >= (d.get("page_count") or 0):
                break
    return out


def agg_smartrecruiters(cfg, opts, terms):
    """SmartRecruiters' own cross-company search (what jobs.smartrecruiters.com uses): every SmartRecruiters
    employer at once, no slugs needed. Undocumented, so it may change."""
    out, seen_ids = [], set()
    for t in terms[: opts.get("max_queries", 8)]:
        for off in range(0, opts.get("max_results", 300), 100):
            d = get_json("https://jobs.smartrecruiters.com/sr-jobs/search?" + urllib.parse.urlencode({"keyword": t, "limit": 100, "offset": off})) or {}
            rows = d.get("content") or []
            for j in rows:
                if j.get("id") in seen_ids:
                    continue
                seen_ids.add(j.get("id"))
                l = j.get("location") or {}
                co = j.get("company") or {}
                loc = _loc(l.get("city"), l.get("region")) + (" (Remote)" if l.get("remote") else "") + (f" [{(l.get('country') or '').upper()}]" if l.get("country") else "")
                b = {"ats": "smartrecruiters", "slug": co.get("identifier", ""), "company": co.get("name", "")}
                out.append(dict(company=co.get("name", ""), ats="smartrecruiters", source="smartrecruiters-search", board=b,
                                id=j.get("id"), title=j.get("name", ""), location=loc,
                                url=j.get("applyUrl") or f"https://jobs.smartrecruiters.com/{b['slug']}/{j.get('id')}",
                                listing_url="", posted=(j.get("releasedDate") or "")[:10], desc=None, pay="",
                                remote_flag=bool(l.get("remote")), employment=(j.get("typeOfEmployment") or {}).get("label", "")))
            if len(rows) < 100:
                break
    return out


def agg_remoteok(cfg, opts, terms):
    d = get_json("https://remoteok.com/api")
    out = []
    for j in d[1:] if isinstance(d, list) else []:
        out.append(agg_job("remoteok", j.get("company"), j.get("position"), f"Remote ({j.get('location') or 'anywhere'})",
                           j.get("url"), [j.get("apply_url")] + ats_links(j.get("description")), j.get("description"),
                           money(j.get("salary_min"), j.get("salary_max")), j.get("date"), True))
    return out


def agg_himalayas(cfg, opts, terms):
    out = []
    country = opts.get("country", "US")
    for t in terms[: opts.get("max_queries", 8)]:
        for page in range(1, opts.get("pages", 2) + 1):
            d = get_json(f"https://himalayas.app/jobs/api/search?q={urllib.parse.quote(t)}&country={country}&page={page}") or {}
            jobs = d.get("jobs") or []
            for j in jobs:
                if re.search(r"contract|part|intern|temporary", j.get("employmentType") or "", re.I):
                    continue
                where = ", ".join(j.get("locationRestrictions") or []) or "anywhere"
                posted = dt.datetime.fromtimestamp(int(j["pubDate"]), dt.timezone.utc).strftime("%Y-%m-%d") if str(j.get("pubDate", "")).isdigit() else ""
                out.append(agg_job("himalayas", j.get("companyName"), j.get("title"), f"Remote ({where})",
                                   j.get("guid") or j.get("applicationLink"), ats_links(j.get("description")), j.get("description"),
                                   money(j.get("minSalary"), j.get("maxSalary"), "$" if (j.get("currency") or "USD") == "USD" else (j.get("currency") or "") + " ", j.get("salaryPeriod") or ""),
                                   posted, True, j.get("employmentType")))
            if len(jobs) < 20:
                break
    return out


def agg_jobicy(cfg, opts, terms):
    d = get_json(f"https://jobicy.com/api/v2/remote-jobs?count=100&geo={opts.get('geo', 'usa')}") or {}
    out = []
    for j in d.get("jobs", []):
        jt = " ".join(j.get("jobType") or []) if isinstance(j.get("jobType"), list) else str(j.get("jobType") or "")
        if re.search(r"contract|part|intern", jt, re.I):
            continue
        out.append(agg_job("jobicy", j.get("companyName"), j.get("jobTitle"), f"Remote ({j.get('jobGeo') or 'anywhere'})",
                           j.get("url"), ats_links(j.get("jobDescription")), j.get("jobDescription"),
                           money(j.get("salaryMin"), j.get("salaryMax")), j.get("pubDate"), True, jt))
    return out


def agg_weworkremotely(cfg, opts, terms):
    code, body = http_status("https://weworkremotely.com/remote-jobs.rss", 40)
    out = []
    if code != 200:
        return out
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        g = lambda t: (it.findtext(t) or "").strip()
        company, _, title = g("title").partition(": ")
        posted = ""
        try:
            posted = dt.datetime.strptime(g("pubDate")[:25], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
        except ValueError:
            pass
        out.append(agg_job("weworkremotely", company, title or company, f"Remote ({g('region') or 'anywhere'})", g("link"),
                           ats_links(g("description")), g("description"), "", posted, True, g("type")))
    return out


def agg_hn(cfg, opts, terms):
    """Hacker News "Ask HN: Who is hiring?" threads (this month and last). Each top-level comment is one employer."""
    d = get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10") or {}
    threads = [h["objectID"] for h in d.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()][: opts.get("threads", 2)]
    out = []
    for tid in threads:
        t = get_json(f"https://hn.algolia.com/api/v1/items/{tid}", timeout=60) or {}
        for c in t.get("children") or []:
            body = c.get("text") or ""
            if not body:
                continue
            first = text(re.split(r"<p>", body, maxsplit=1)[0])
            parts = [p.strip() for p in re.split(r"\s+[|—–]\s+|\s+-\s+", first) if p.strip()]
            if len(parts) < 2:
                continue
            remote = bool(re.search(r"\bremote\b", first, re.I))
            company = re.sub(r"https?://\S+|\(.*?\)|\[.*?\]", " ", parts[0])
            company = re.sub(r"\s+", " ", company).strip(" |-,.\u2014") or parts[0]
            out.append(agg_job("hn", company[:80], first[:200], first[:200],
                               f"https://news.ycombinator.com/item?id={c.get('id')}", ats_links(body), body, "",
                               c.get("created_at"), remote))
    return out


def _queries(cfg, opts, terms):
    """(term, place) pairs: each term near the metro, plus each term remote, capped at max_queries."""
    loc = cfg.get("location") or {}
    metro = opts.get("location") or loc.get("metro") or ""
    pairs = []
    for t in terms:
        if metro and cfg["filters"].get("allow_local", True):
            pairs.append((t, metro))
        if cfg["filters"].get("allow_remote_us", True):
            pairs.append((t, "remote"))
    return pairs[: opts.get("max_queries", 12)]


def agg_adzuna(cfg, opts, terms):
    out = []
    radius_km = int((cfg.get("location") or {}).get("radius_miles", 30) * 1.6)
    for t, place in _queries(cfg, opts, terms):
        q = {"app_id": opts["app_id"], "app_key": opts["app_key"], "results_per_page": 50, "max_days_old": opts.get("max_days_old", 7),
             "sort_by": "date", "what": t + (" remote" if place == "remote" else ""), "content-type": "application/json"}
        if place != "remote":
            q.update(where=place, distance=radius_km)
        d = get_json(f"https://api.adzuna.com/v1/api/jobs/{opts.get('country', 'us')}/search/1?" + urllib.parse.urlencode(q)) or {}
        for j in d.get("results", []):
            if (j.get("contract_time") or "") == "part_time" or (j.get("contract_type") or "") == "contract":
                continue
            loc = (j.get("location") or {}).get("display_name", "")
            out.append(agg_job("adzuna", (j.get("company") or {}).get("display_name"), j.get("title"),
                               loc + (" (Remote)" if place == "remote" else ""), j.get("redirect_url"), [], j.get("description"),
                               money(j.get("salary_min"), j.get("salary_max")) if str(j.get("salary_is_predicted")) != "1" else "",
                               j.get("created"), place == "remote" or None))
    return out


def agg_usajobs(cfg, opts, terms):
    out = []
    hdr = {"Host": "data.usajobs.gov", "User-Agent": opts["email"], "Authorization-Key": opts["api_key"]}
    for t, place in _queries(cfg, opts, terms):
        q = {"Keyword": t, "DatePosted": opts.get("max_days_old", 7), "ResultsPerPage": 100}
        if place == "remote":
            q["RemoteIndicator"] = "True"
        else:
            q.update(LocationName=place, Radius=(cfg.get("location") or {}).get("radius_miles", 30))
        d = get_json("https://data.usajobs.gov/api/search?" + urllib.parse.urlencode(q), headers=hdr) or {}
        for item in ((d.get("SearchResult") or {}).get("SearchResultItems") or []):
            m = item.get("MatchedObjectDescriptor") or {}
            rem = (m.get("PositionRemuneration") or [{}])[0]
            det = ((m.get("UserArea") or {}).get("Details") or {})
            out.append(agg_job("usajobs", m.get("OrganizationName"), m.get("PositionTitle"),
                               m.get("PositionLocationDisplay", "") + (" (Remote)" if place == "remote" else "") + " [US]",
                               m.get("PositionURI"), [], f"{det.get('JobSummary', '')} {m.get('QualificationSummary', '')}",
                               money(rem.get("MinimumRange"), rem.get("MaximumRange"), "$", rem.get("Description", "")),
                               m.get("PublicationStartDate"), place == "remote" or None))
    return out


def agg_jooble(cfg, opts, terms):
    out = []
    for t, place in _queries(cfg, opts, terms):
        body = {"keywords": t + (" remote" if place == "remote" else ""), "page": "1"}
        if place != "remote":
            body.update(location=place, radius=str((cfg.get("location") or {}).get("radius_miles", 30)))
        d = get_json(f"https://jooble.org/api/{opts['api_key']}", data=body) or {}
        for j in d.get("jobs", []):
            out.append(agg_job("jooble", j.get("company"), j.get("title"), j.get("location", "") + (" (Remote)" if place == "remote" else ""),
                               j.get("link"), [], j.get("snippet"), j.get("salary"), j.get("updated"), place == "remote" or None,
                               j.get("type")))
    return out


def agg_serpapi(cfg, opts, terms):
    opts = dict({"max_queries": 4}, **opts)  # free plan: 250 searches a month = about 4 per run at two runs a day
    """Google Jobs through SerpApi: Google indexes LinkedIn, Indeed, Glassdoor, ZipRecruiter and company career pages,
    and lists every place a job can be applied for, so this is the widest net. Paid per search (free tier exists)."""
    out = []
    for t, place in _queries(cfg, opts, terms):
        q = {"engine": "google_jobs", "api_key": opts["api_key"], "hl": "en", "gl": "us",
             "q": t + (" remote" if place == "remote" else ""), "chips": opts.get("chips", "date_posted:3days")}
        if place != "remote":
            q["location"] = place
        else:
            q["ltype"] = "1"
        d = get_json("https://serpapi.com/search.json?" + urllib.parse.urlencode(q), timeout=60) or {}
        for j in d.get("jobs_results", []):
            ex = j.get("detected_extensions") or {}
            links = [a.get("link") for a in j.get("apply_options") or []]
            if re.search(r"contract|part", ex.get("schedule_type") or "", re.I):
                continue
            out.append(agg_job("google-jobs", j.get("company_name"), j.get("title"),
                               (j.get("location") or "") + (" (Remote)" if ex.get("work_from_home") or place == "remote" else ""),
                               j.get("share_link") or (links[0] if links else ""), links, j.get("description"),
                               ex.get("salary", ""), "", bool(ex.get("work_from_home")) or None, ex.get("schedule_type")))
            out[-1]["via"] = j.get("via", "")
    return out


def agg_jsearch(cfg, opts, terms):
    opts = dict({"max_queries": 3}, **opts)  # free plan: 200 requests a month = about 3 per run at two runs a day
    """JSearch on RapidAPI: also built on Google Jobs; includes each job's apply links. Free tier is small."""
    out = []
    hdr = {"X-RapidAPI-Key": opts["api_key"], "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    for t, place in _queries(cfg, opts, terms):
        q = {"query": f"{t} in {place}" if place != "remote" else f"{t} remote", "page": 1, "num_pages": 1,
             "country": "us", "date_posted": opts.get("date_posted", "3days")}
        if place == "remote":
            q["work_from_home"] = "true"
        d = get_json("https://jsearch.p.rapidapi.com/search?" + urllib.parse.urlencode(q), headers=hdr, timeout=60) or {}
        for j in d.get("data", []) if isinstance(d, dict) else []:
            if re.search(r"contract|part|intern", j.get("job_employment_type") or "", re.I):
                continue
            links = [j.get("job_apply_link")] + [a.get("apply_link") for a in j.get("apply_options") or []]
            out.append(agg_job("jsearch", j.get("employer_name"), j.get("job_title"),
                               _loc(j.get("job_city"), j.get("job_state"), j.get("job_country")) + (" (Remote)" if j.get("job_is_remote") else ""),
                               j.get("job_google_link") or links[0], links, j.get("job_description"),
                               money(j.get("job_min_salary"), j.get("job_max_salary"), "$", (j.get("job_salary_period") or "").lower()),
                               j.get("job_posted_at_datetime_utc"), bool(j.get("job_is_remote")) or None, j.get("job_employment_type")))
    return out


# name -> (function, keys it needs, on by default when nothing is configured, one-line description)
AGGREGATORS = {
    "smartrecruiters": (agg_smartrecruiters, [], True, "SmartRecruiters search across every company on it, no key"),
    "themuse": (agg_themuse, [], True, "The Muse: large US index, entry/mid level, local + remote, no key"),
    "remoteok": (agg_remoteok, [], True, "Remote OK: newest remote jobs, no key"),
    "remotive": (agg_remotive, [], True, "Remotive: remote software jobs (one call per run; they allow ~4 a day), no key"),
    "himalayas": (agg_himalayas, [], True, "Himalayas: large remote-job index searchable by keyword and country, no key"),
    "jobicy": (agg_jobicy, [], True, "Jobicy: remote jobs open to the US, no key"),
    "weworkremotely": (agg_weworkremotely, [], True, "We Work Remotely RSS, no key"),
    "hn": (agg_hn, [], True, "Hacker News 'Who is hiring?' threads (startups, many not posted elsewhere), no key"),
    "adzuna": (agg_adzuna, ["app_id", "app_key"], False, "Adzuna: broad US aggregator incl. local non-tech employers; free key at developer.adzuna.com"),
    "usajobs": (agg_usajobs, ["api_key", "email"], False, "USAJOBS: every federal job; free key at developer.usajobs.gov"),
    "jooble": (agg_jooble, ["api_key"], False, "Jooble: broad aggregator; free key at jooble.org/api/about"),
    "serpapi": (agg_serpapi, ["api_key"], False, "Google Jobs via SerpApi: covers LinkedIn, Indeed, Glassdoor, ZipRecruiter and company sites; serpapi.com"),
    "jsearch": (agg_jsearch, ["api_key"], False, "Google Jobs via JSearch (RapidAPI); rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"),
}


def aggregator_plan(cfg):
    """[(name, opts, missing_keys)] for every aggregator, honouring config "aggregators" ({name: {enabled, ...keys}})."""
    conf = cfg.get("aggregators") or {}
    plan = []
    for name, (fn, keys, default_on, _) in AGGREGATORS.items():
        o = dict(conf.get(name) or {})
        for k in keys:  # keys can also come from the environment, e.g. ADZUNA_APP_KEY
            o.setdefault(k, os.environ.get(f"{name}_{k}".upper(), ""))
        on = o.get("enabled", default_on or all(o.get(k) for k in keys))
        missing = [k for k in keys if not o.get(k)]
        plan.append((name, o, on, missing))
    return plan


def fetch_aggregators(cfg, terms):
    """(jobs, per-source counts, problems)"""
    jobs, counts, problems = [], {}, []
    todo = []
    for name, o, on, missing in aggregator_plan(cfg):
        if not on:
            continue
        if missing:
            problems.append(f"{name}: needs {', '.join(missing)}")
            continue
        todo.append((name, o))

    def one(item):
        name, o = item
        try:
            return name, AGGREGATORS[name][0](cfg, o, terms), None
        except Exception as e:  # one source failing never stops the run
            return name, [], f"{name}: {type(e).__name__}: {e}"[:200]
    with cf.ThreadPoolExecutor(6) as ex:
        for name, got, err in ex.map(one, todo):
            counts[name] = len(got)
            if err:
                problems.append(err)
            elif not got:
                problems.append(f"{name}: returned nothing (blocked, key rejected, or no matches)")
            jobs.extend(got)
    return jobs, counts, problems


# ---------- resolving job-board listings to the employer's own posting ----------
RESOLVE_ATS = ["greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "bamboohr", "breezy", "rippling", "gem"]
CO_SUFFIX = re.compile(r"[,.]?\s+(inc|llc|ltd|corp|corporation|co|company|technologies|technology|labs|hq|group|holdings|software|systems|ai)\.?$", re.I)


def slug_guesses(company):
    base = re.sub(r"\(.*?\)|\[.*?\]", "", (company or "").lower()).strip()
    base = re.sub(r"\.(com|io|ai|co|app|dev)\b", "", base)
    names = [base, CO_SUFFIX.sub("", base)]
    out = []
    for n in names:
        n = n.replace("&", "and")
        for g in (re.sub(r"[^a-z0-9]", "", n), re.sub(r"[^a-z0-9]+", "-", n).strip("-")):
            if g and len(g) > 1 and g not in out:
                out.append(g)
    return out[:3]


def norm_title(t):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (t or "").lower())
    t = re.sub(r"\b(remote|hybrid|onsite|on-site|us|usa|united states|full[- ]time)\b", " ", t)
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", t).split())


def title_match(want, jobs):
    """The board job whose title is the listing's title (allowing for location tags), or None."""
    w = norm_title(want)
    if not w:
        return None
    ws = set(w.split())
    best, score = None, 0.0
    for j in jobs:
        t = norm_title(j["title"])
        if not t:
            continue
        if t == w:
            return j
        ts = set(t.split())
        if len(ts) >= 2 and (f" {t} " in f" {w} "):  # the board title appears inside a long listing line (HN)
            s = 0.9 + len(ts) / 100
        else:
            s = len(ws & ts) / max(len(ws | ts), 1)
        if s > score:
            best, score = j, s
    return best if score >= 0.75 else None


def is_board_root(url):
    """True for a link to a company's whole job board rather than one posting."""
    b = board_from_url(url)
    if not b or b["ats"] == "workday":
        return False
    path = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    if path and path[0].lower() == (b.get("slug") or "").lower():
        path = path[1:]
    return not [p for p in path if p.lower() not in ("jobs", "careers", "en", "en-us", "")]


def resolve_leads(leads, cfg, budget=120, also_have=()):
    """For job-board leads (apply route "check"), find the same job on the employer's own board.
    Checks watchlist boards first, then probes likely slugs. Returns (resolved count, boards to add)."""
    by_name = {}
    for b in cfg["watchlist"]:
        for n in {re.sub(r"[^a-z0-9]", "", (b.get("company") or "").lower()), (b.get("slug") or "").lower()}:
            if n:
                by_name.setdefault(n, []).append(b)
    todo = [l for l in leads if l.get("company") and (route_for_url(l["url"]) == "check" or is_board_root(l["url"]))]
    companies = []
    for l in todo:
        k = re.sub(r"[^a-z0-9]", "", l["company"].lower())
        if k and k not in companies:
            companies.append(k)
    companies = companies[:budget]
    cache = {}  # (ats, slug) -> jobs or None
    lock = threading.Lock()

    def jobs_on(b):
        ident = board_ident(b)
        with lock:
            if ident in cache:
                return cache[ident]
        _, jobs = fetch_board((dict(b), [""]))
        with lock:
            cache[ident] = jobs
        return jobs

    def boards_for(l):
        if is_board_root(l["url"]):  # a link to the company's whole board (common on HN): look inside it
            return [board_from_url(l["url"])], True
        k = re.sub(r"[^a-z0-9]", "", l["company"].lower())
        known = [b for g in [k] + slug_guesses(l["company"]) for b in by_name.get(g, [])]
        if known:
            return known, False
        if k not in companies:
            return [], False
        return [{"ats": a, "slug": s, "company": l["company"]} for s in slug_guesses(l["company"]) for a in RESOLVE_ATS], True

    def one(l):
        boards, probed = boards_for(l)
        for b in boards:
            jobs = jobs_on(b)
            if not jobs:
                continue
            hit = title_match(l["title"], jobs)
            if hit:
                return l, hit, (b if probed else None)
        return l, None, None

    resolved, add, have = 0, [], {board_ident(b) for b in cfg["watchlist"]} | set(also_have)
    with cf.ThreadPoolExecutor(16) as ex:
        for l, hit, newb in ex.map(one, todo):
            if not hit:
                continue
            if not l.get("listing_url"):
                l["listing_url"] = l["url"]
            for k in ("url", "ats", "board", "id"):
                l[k] = hit.get(k, l.get(k))
            l["title"] = hit["title"] if l.get("source") == "hn" else l["title"]
            if hit.get("desc"):
                l["desc"] = hit["desc"]
            elif len(l.get("desc") or "") < 600:
                l["desc"] = None  # enrich fetches the employer's full description
            if hit.get("location"):
                l["location"] = hit["location"]
            if hit.get("pay") and not l.get("pay"):
                l["pay"] = hit["pay"]
            l["key"] = job_key(l["url"])
            l["resolved"] = True  # its location came from the employer's posting: finish re-checks the region
            resolved += 1
            if newb and board_ident(newb) not in have:
                newb["via"], newb["added"] = l.get("source", "resolve"), dt.date.today().isoformat()
                have.add(board_ident(newb))
                add.append(newb)
    return resolved, add


def resolve_cmd(args):
    """Resolve a leads or connector-leads file in place (for leads Claude collected by hand)."""
    cfg = json.load(open(args.config))
    rows = json.load(open(args.input))
    for r in rows:
        r.setdefault("desc", r.get("description") or "")
        r.setdefault("listing_url", "")
        r["_row_id"] = r.get("id")  # the caller's id (an HQ job id) survives resolution
    n, add = resolve_leads(rows, cfg, budget=args.budget)
    for r in rows:
        r["id"] = r.pop("_row_id")
        r.pop("board", None)
        if "key" in r:
            r["key"] = job_key(r.get("url"))
        if r.get("desc") and not r.get("description"):
            r["description"] = r["desc"]
        r.pop("desc", None)
        r["apply_route"] = route_for_url(r.get("url"))
    json.dump(rows, open(args.input, "w"), indent=1, ensure_ascii=False)
    if add:
        cfg["watchlist"].extend(add)
        json.dump(cfg, open(args.config, "w"), indent=1)
    print(json.dumps({"rows": len(rows), "resolved_to_employer": n, "boards_added": [f"{b['ats']}:{b['slug']}" for b in add]}, indent=1))


def peek_cmd(args):
    """One line per lead, for a first pass over a long leads file before reading descriptions."""
    rows = json.load(open(args.input))
    for i, r in enumerate(rows):
        print(" | ".join(str(x) for x in [i, r.get("company", ""), r.get("title", "")[:90], r.get("location", "")[:50],
                                          r.get("region", ""), r.get("pay", "") or "-", r.get("years", "") or "-",
                                          r.get("source", ""), r.get("apply_route", ""), ",".join(r.get("flags") or [])]))


def sources_cmd(args):
    cfg = json.load(open(args.config))
    for name, o, on, missing in aggregator_plan(cfg):
        state = "on" if on and not missing else ("needs " + ", ".join(missing) if on or missing else "off")
        print(f"{name:15} {state:28} {AGGREGATORS[name][3]}")


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
    if j.get("ats") == "bamboohr" and j.get("desc") is None:
        d = get_json(BAMBOO_JOB.format(s=j["board"]["slug"], id=j["id"])) or {}
        op = (d.get("result") or {}).get("jobOpening") or {}
        j["desc"] = text(op.get("description", ""))
        if op.get("compensation"):
            j["pay"] = str(op["compensation"])
        j["posted"] = (op.get("datePosted") or "")[:10]
    if j.get("ats") == "rippling" and j.get("desc") is None:
        d = get_json(RIPPLING_JOB.format(s=j["board"]["slug"], id=j["id"])) or {}
        desc = d.get("description") or {}
        j["desc"] = text(" ".join(str(v) for v in desc.values()) if isinstance(desc, dict) else str(desc))
        j["posted"] = (d.get("createdOn") or "")[:10]
    if j.get("ats") == "workable" and j.get("desc") is None:
        with _WORKABLE_LOCK:
            time.sleep(1.5)
            d = get_json(f"https://apply.workable.com/api/v2/accounts/{j['board']['slug']}/jobs/{j['id']}") or {}
        j["desc"] = " ".join(text(d.get(k, "")) for k in ("description", "requirements", "benefits"))
    if j.get("desc") is None and j.get("url"):  # breezy and anything else: read the posting page itself
        code, body = http_status(j["url"], 30, 800_000)
        j["desc"] = text(re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body)) if code == 200 else ""
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
    new, by_title, by_key = [], {}, {}
    for j in cands:
        tk = title_key(j["company"], j["title"])
        if j["key"] in tracked or j["key"] in seen or tk in tracked_titles:
            continue
        first = by_key.get(j["key"]) or by_title.get(tk)
        if first is not None:  # same role posted in several places: keep one, note the rest
            if route_for_url(first["url"]) == "check" and route_for_url(j["url"]) != "check":
                # the same job on its employer's own site beats a job-board copy
                j["other_locations"] = first["other_locations"] + ([first["location"]] if first.get("location") and first.get("location") != j.get("location") else [])
                j["also_on"] = first.get("also_on", []) + [first.get("listing_url") or first["url"]]
                new[new.index(first)] = j
                by_title[title_key(first["company"], first["title"])] = by_title[tk] = j
                by_key[first["key"]] = by_key[j["key"]] = j
                seen[first["key"]] = today
                continue
            if j.get("location") and j.get("location") != first.get("location"):
                first["other_locations"].append(j.get("location", ""))
            if j.get("source") != first.get("source"):
                first.setdefault("also_on", []).append(j.get("listing_url") or j["url"])
            seen[j["key"]] = today
            continue
        j["other_locations"] = []
        by_title[tk] = j
        by_key[j["key"]] = j
        new.append(j)
    with cf.ThreadPoolExecutor(12) as ex:
        new = list(ex.map(enrich, new))
    out, too_senior, dropped_loc, too_old = [], 0, 0, 0
    f = cfg["filters"]
    maxy, maxpay = f.get("max_years_required"), f.get("max_pay_floor")
    max_age = f.get("max_age_days")
    oldest = (dt.date.today() - dt.timedelta(days=max_age)).isoformat() if max_age else ""
    for j in new:
        seen[j["key"]] = today
        if j.get("resolved") and j.get("ats") != "workday":
            region = classify_location(j, c)
            if not region:
                dropped_loc += 1
                continue
            j["region"] = region
        if oldest and re.match(r"\d{4}-\d{2}-\d{2}$", j.get("posted") or "") and j["posted"] < oldest:
            too_old += 1
            continue
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
                        apply_route=route_for_url(j["url"]), listing_url=j.get("listing_url") or "",
                        also_on=j.get("also_on", []), via=j.get("via", ""),
                        flags=flags, description=j["desc"][: args.desc_chars]))
    out.sort(key=lambda r: (r["region"] != c["local_label"], r["company"].lower(), r["title"]))
    # A company posting dozens of near-identical openings (call centres, staffing firms, sales agencies)
    # shouldn't bury everything else: keep the newest few per company, local ones first.
    cap = f.get("max_per_company", 4)
    capped = {}
    if cap:
        by_co = {}
        for r in sorted(out, key=lambda r: (r["region"] != c["local_label"], r.get("posted") or "0000"), reverse=False):
            by_co.setdefault(re.sub(r"[^a-z0-9]", "", r["company"].lower()), []).append(r)
        keep = set()
        for co, rows in by_co.items():
            rows.sort(key=lambda r: (r["region"] != c["local_label"], "".join(chr(255 - ord(ch)) for ch in (r.get("posted") or ""))))
            for r in rows[:cap]:
                keep.add(id(r))
            if len(rows) > cap:
                capped[rows[0]["company"]] = len(rows) - cap
        out = [r for r in out if id(r) in keep]
    prev = []
    if getattr(args, "append", False):
        try:
            prev = json.load(open(args.out))
        except Exception:
            prev = []
    json.dump(prev + out, open(args.out, "w"), indent=1, ensure_ascii=False)
    json.dump(seen, open(args.seen, "w"), indent=0, sort_keys=True)
    summary = dict(date=today, matched_filters=len(cands), already_tracked_or_seen=len(cands) - len(new),
                   dropped_as_too_senior=too_senior, dropped_as_older_than_max_age=too_old,
                   dropped_over_per_company_cap=sum(capped.values()), capped_companies=capped,
                   dropped_location_after_detail=dropped_loc, new_leads=len(out))
    summary.update(extra_summary)
    print(json.dumps(summary, indent=1))


def passes_title(j, c):
    return c["include"].search(j["title"] or "") and not (c["exclude"] and c["exclude"].search(j["title"] or ""))


def bulk_boards(cfg):
    """(boards, problems) from the public board lists named in config "bulk_lists"."""
    have = {board_ident(b) for b in cfg["watchlist"]}
    out, problems = [], []
    for ats in cfg.get("bulk_lists") or []:
        if ats not in BULK_OK:
            problems.append(f"bulk list {ats}: not supported (too slow or no list)")
            continue
        code, body = http_status(BULK_LIST_URL.format(ats=ats), 60, 20_000_000)
        if code != 200:
            problems.append(f"bulk list {ats}: HTTP {code}")
            continue
        import csv, io
        for row in csv.DictReader(io.StringIO(body)):
            slug = (row.get("slug") or "").strip()
            if not slug:
                continue
            name = (row.get("name") or slug).strip()
            if re.search(r"sandbox|\b(test|testing|demo|staging|training environment|candidate \d)\b", f"{name} {slug}", re.I):
                continue  # vendor test accounts that show up in the public lists
            b = {"ats": ats, "slug": slug, "company": name, "bulk": True}
            if board_ident(b) not in have:
                have.add(board_ident(b))
                out.append(b)
    return out, problems


def search_terms(cfg):
    terms = cfg.get("search_terms") or cfg.get("workday_search_terms") or []
    return [t for t in terms if t and not t.startswith("EXAMPLE")]


def board_ident(b):
    return (b["ats"], (b.get("slug") or b.get("host") or "").lower())


def candidate(j, c, args):
    """Region for a job that passes the title, location and employment-type filters, else None."""
    if not passes_title(j, c):
        return None
    if not args.include_contract and re.search(r"\b(part[- ]time|intern|internship|contract|contractor|temporary|temp|freelance|seasonal)\b", j.get("title") or "", re.I):
        return None
    if j.get("ats") == "workday" and re.search(r"\d+ Locations", j.get("location") or ""):
        return "pending"  # resolved after the detail fetch
    region = classify_location(j, c)
    if not region:
        return None
    if j.get("employment") and re.search(r"intern|contract|part|temporary|freelance", j["employment"], re.I) and not args.include_contract:
        return None
    return region


def run(args):
    cfg = json.load(open(args.config))
    c = compile_cfg(cfg)
    seen, tracked, tracked_titles = load_state(args)
    wd_terms = cfg.get("workday_search_terms") or DEFAULT_WD_TERMS
    terms = search_terms(cfg)
    agg_jobs, agg_counts, problems = [], {}, []
    if not args.no_aggregators:
        agg_jobs, agg_counts, problems = fetch_aggregators(cfg, terms)
    agg_cands = []
    for j in agg_jobs:
        region = candidate(j, c, args)
        if region and region != "pending":
            j["region"], j["key"] = region, job_key(j["url"])
            agg_cands.append(j)
    # Grow the watchlist: a fitting listing that links to a company board we don't watch yet adds that whole board.
    have = {board_ident(b) for b in cfg["watchlist"]}
    grown = []
    if not args.no_grow:
        for j in agg_cands:
            b = board_from_url(j["url"])
            if b and board_ident(b) not in have and (b["ats"] in NO_ACCOUNT or b["ats"] == "workday"):
                if j.get("company"):
                    b["company"] = j["company"]
                b["via"], b["added"] = j["source"], dt.date.today().isoformat()
                have.add(board_ident(b))
                grown.append(b)
    bulk = []
    if not args.only_aggregators and not args.no_bulk:
        bulk, bp = bulk_boards(cfg)
        problems += bp
        bulk = [b for b in bulk if board_ident(b) not in {board_ident(g) for g in grown}]
    boards = [] if args.only_aggregators else cfg["watchlist"] + grown + bulk
    dead, total, cands = [], 0, []
    keep_grown, bulk_dead = [], 0
    with cf.ThreadPoolExecutor(32 if bulk else 16) as ex:
        for b, jobs in ex.map(fetch_board, [(b, wd_terms) for b in boards]):
            if jobs is None:
                if b.get("bulk"):
                    bulk_dead += 1
                elif b not in grown:
                    dead.append(f"{b['ats']}:{b.get('slug') or b.get('host')}")
                continue
            if b in grown:
                keep_grown.append(b)
            total += len(jobs)
            for j in jobs:
                region = candidate(j, c, args)
                if region:
                    j["region"], j["key"], j["source"] = region, job_key(j["url"]), j["ats"]
                    cands.append(j)
    for j in cands:
        if j["region"] == "pending":
            wd_detail(j)
            j["region"] = classify_location(j, c) or "pending"
    cands = [j for j in cands if j["region"] != "pending"]
    # aggregator rows go after the boards, so a job seen on its own board keeps the board's richer record
    fresh = [j for j in agg_cands if j["key"] not in seen and j["key"] not in tracked
             and title_key(j["company"], j["title"]) not in tracked_titles]
    resolved, found = (0, []) if args.no_resolve else resolve_leads(
        fresh, cfg, also_have={board_ident(b) for b in keep_grown + bulk})
    if not args.no_grow:
        keep_grown += found
    cands += agg_cands
    if keep_grown:
        cfg["watchlist"].extend(keep_grown)
        cfg["watchlist"].sort(key=lambda b: ((b.get("slug") or b.get("host") or "").lower(), b["ats"]))
        json.dump(cfg, open(args.config, "w"), indent=1)
    finish(cfg, c, args, cands, seen, tracked, tracked_titles,
           dict(boards=len(boards), watchlist_boards=len(cfg["watchlist"]) - len(keep_grown), bulk_boards=len(bulk),
                bulk_unreachable=bulk_dead, boards_unreachable=len(dead), postings_scanned=total, unreachable=dead,
                aggregator_rows=agg_counts, aggregator_matches=len(agg_cands), resolved_to_employer=resolved,
                boards_added=[f"{b['ats']}:{b.get('slug') or b.get('host')} ({b['company']}, via {b['via']})" for b in keep_grown],
                aggregator_problems=problems))


def ingest(args):
    cfg = json.load(open(args.config))
    c = compile_cfg(cfg)
    seen, tracked, tracked_titles = load_state(args)
    rows = json.load(open(args.input))
    cands, skipped = [], 0
    for r in rows:
        j = dict(company=r.get("company", ""), title=r.get("title", ""), location=r.get("location", ""),
                 url=r.get("url", ""), desc=r.get("description") or "", pay=r.get("pay", ""), posted=r.get("posted", ""),
                 remote_flag=bool(r.get("remote")), ats=r.get("ats", ""), source=r.get("source", "connector"),
                 listing_url=r.get("listing_url", ""), employment=r.get("employment", ""))
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
    fresh = [j for j in cands if j["key"] not in seen and j["key"] not in tracked
             and title_key(j["company"], j["title"]) not in tracked_titles]
    resolved, found = (0, []) if args.no_resolve else resolve_leads(fresh, cfg)
    if found:
        cfg["watchlist"].extend(found)
        json.dump(cfg, open(args.config, "w"), indent=1)
    finish(cfg, c, args, cands, seen, tracked, tracked_titles,
           dict(input_rows=len(rows), failed_filters=skipped, resolved_to_employer=resolved,
                boards_added=[f"{b['ats']}:{b['slug']}" for b in found]))


def probe(args):
    cfg = json.load(open(args.config))
    have = {board_ident(b) for b in cfg["watchlist"]}
    added = []

    def count(b):
        bb, jobs = fetch_board((dict(b), [""]))
        return None if jobs is None else len(jobs)

    def try_one(s):
        named = board_from_url(s) if s.startswith("http") else None
        if named:  # the URL names its ATS: check only that one, so unrelated companies sharing the slug aren't added
            n = count(named)
            return s, ([(named, n)] if n else [])
        if s.startswith("http"):
            return s, []
        hits = []
        for ats in PROBE_ORDER:
            b = {"ats": ats, "slug": s, "company": s}
            n = count(b)
            if n:
                hits.append((b, n))
        return s, hits

    with cf.ThreadPoolExecutor(12) as ex:
        for s, hits in ex.map(try_one, args.targets):
            if not hits:
                print(f"{s}: not found")
            for b, n in hits:
                ident = board_ident(b)
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
    b = board_from_url(s) if s.startswith("http") else None
    if not b:
        if not args.ats:
            sys.exit("give --ats or a board URL")
        b = {"ats": args.ats, "slug": s, "company": s}
    terms = [args.grep] if (b["ats"] == "workday" and args.grep) else [""]
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
        r.add_argument("--no-resolve", action="store_true", help="don't look for job-board listings on employer boards")
        if name == "run":
            r.add_argument("--no-aggregators", action="store_true", help="company boards only")
            r.add_argument("--only-aggregators", action="store_true", help="aggregators only (skip the watchlist boards)")
            r.add_argument("--no-grow", action="store_true", help="don't add boards found through aggregators to the watchlist")
            r.add_argument("--no-bulk", action="store_true", help="skip the public board lists in config bulk_lists")
        if name == "ingest":
            r.add_argument("--input", required=True, help="JSON list of leads from job-board connectors")
    bd = sp.add_parser("board")
    bd.add_argument("target", help="board URL, or a slug together with --ats")
    bd.add_argument("--ats", choices=PROBE_ORDER)
    bd.add_argument("--grep", help="words that must all appear in the title")
    rs = sp.add_parser("resolve")
    rs.add_argument("--config", default="config.json")
    rs.add_argument("--input", required=True, help="JSON list of {company, title, url, ...}; rewritten in place")
    rs.add_argument("--budget", type=int, default=120, help="most companies to probe")
    pk = sp.add_parser("peek")
    pk.add_argument("input")
    so = sp.add_parser("sources")
    so.add_argument("--config", default="config.json")
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
    {"run": run, "ingest": ingest, "probe": probe, "board": board, "alive": alive, "account": account_cmd,
     "sources": sources_cmd, "resolve": resolve_cmd, "peek": peek_cmd}[a.cmd](a)
