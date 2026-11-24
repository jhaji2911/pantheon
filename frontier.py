"""The research frontier: recent papers the residents can build on, ranked for novelty.

The residents used to propose questions out of their own heads, which meant textbook results
(recover an LCG's state, derive a known bound). This module keeps a pool of *recent* papers
instead — arXiv and OpenAlex (Google Scholar has no API and blocks scrapers; OpenAlex indexes
the same literature) — and scores each one so a resident is shown work worth extending,
testing or contradicting:

    recency          newer is better (half-life ~3 weeks)
    open question    "we conjecture", "remains unclear", "fails to", "contrary to" ...
    testable         simulation / benchmark / code / dataset: Quorum can actually run something
    domain fit       overlap with the resident's domain vocabulary; two domains earns a bonus
    novelty          1 - similarity to what the colony has already proposed or written up
    penalties        surveys, tutorials, position pieces, "a review of"

`refresh()` fetches and scores; `for_domain()` is what a resident's observation shows;
`check_proposal()` is the gate a research proposal must pass (a cited paper or a prior colony
finding, a falsifiable hypothesis, a concrete test, and not a rewording of earlier work).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import store

REFRESH_EVERY = 3 * 3600
WINDOW_DAYS = 75
UA = "mist-console/1.0 (research scout)"

# domain -> arXiv categories, and the vocabulary that marks a paper as that domain's
DOMAINS = {
    "cyber": {"cats": ["cs.CR", "cs.CL", "cs.MA"],
              "vocab": "security vulnerability exploit attack adversarial cryptography malware fuzzing "
                       "prompt injection agent sandbox authentication privacy intrusion side-channel"},
    "orbital": {"cats": ["astro-ph.EP", "astro-ph.IM", "physics.space-ph", "astro-ph.SR"],
                "vocab": "orbit satellite orbital trajectory exoplanet telescope spacecraft planetary "
                         "astrometry photometry debris constellation gravitational perturbation"},
    "climate": {"cats": ["physics.ao-ph", "physics.geo-ph", "stat.AP"],
                "vocab": "climate weather atmosphere ocean precipitation emission carbon forecast "
                         "downscaling reanalysis hydrology drought temperature extreme"},
    "quantum": {"cats": ["quant-ph", "cond-mat.str-el"],
                "vocab": "quantum qubit circuit error mitigation entanglement hamiltonian variational "
                         "simulation noise decoherence tensor network fidelity"},
    "brief": {"cats": ["cs.AI", "cs.LG", "cs.IR"],
              "vocab": "language model reasoning retrieval agent evaluation benchmark planning memory "
                       "alignment scaling inference"},
    "world": {"cats": ["cs.MA", "cs.GR", "cs.AI"],
              "vocab": "multi-agent simulation emergent social world model procedural generation "
                       "rendering physics crowd navigation behavior cognitive architecture"},
}

OPEN_QUESTION = re.compile(
    r"\b(we conjecture|conjecture|open (problem|question)|remains? (unclear|open|unknown|unexplained)|"
    r"fails? to|contrary to|counter-?intuitive|surprising(ly)?|we hypothesi[sz]e|unexpected(ly)?|"
    r"in contrast to (prior|previous)|challenge[sd]? (the )?(assumption|belief)|counterexample|"
    r"no (known|existing) (method|approach)|gap between|breaks? down|limitation)\b", re.I)
TESTABLE = re.compile(
    r"\b(simulat\w+|numerical\w*|benchmark\w*|open-?source|code (is )?(available|released)|dataset|"
    r"empirical\w*|we (release|open-source)|reproduc\w+|ablation|monte carlo|experiment\w*)\b", re.I)
DULL = re.compile(r"\b(survey|a review|systematic review|tutorial|perspective|position paper|overview of|"
                  r"roadmap|vision paper|lecture notes|proceedings|workshop report)\b", re.I)
STOP = set("a an the of and or to in on for with by from as is are be this that we our it its at into "
           "via using use based new novel approach method study paper results show can than their".split())


def tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", (text or "").lower()) if w not in STOP}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ------------------------------------------------------------------ fetching
def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _arxiv(domain: str, since: dt.date, per: int = 25) -> list:
    cats = " OR ".join("cat:" + c for c in DOMAINS[domain]["cats"])
    q = "(%s) AND submittedDate:[%s0000 TO 99991231]" % (cats, since.strftime("%Y%m%d"))
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": per})
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in ET.fromstring(_get(url)).findall("a:entry", ns):
        aid = (e.findtext("a:id", "", ns) or "").rsplit("/abs/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid)
        out.append({"id": "arxiv:" + aid, "source": "arxiv", "url": "https://arxiv.org/abs/" + aid,
                    "title": " ".join((e.findtext("a:title", "", ns) or "").split()),
                    "abstract": " ".join((e.findtext("a:summary", "", ns) or "").split()),
                    "authors": ", ".join(a.findtext("a:name", "", ns) for a in e.findall("a:author", ns))[:200],
                    "published": (e.findtext("a:published", "", ns) or "")[:10], "cited": 0, "hint": domain})
    return out


def _openalex(domain: str, since: dt.date, per: int = 20) -> list:
    words = " ".join(DOMAINS[domain]["vocab"].split()[:6])
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode({
        "search": words, "per-page": per, "sort": "publication_date:desc",
        "filter": "from_publication_date:%s,has_abstract:true,type:article|preprint" % since.isoformat()})
    out = []
    for w in json.loads(_get(url)).get("results", []):
        inv = w.get("abstract_inverted_index") or {}
        slots = {}
        for word, idxs in inv.items():
            for i in idxs:
                slots[i] = word
        out.append({"id": "openalex:" + w["id"].rsplit("/", 1)[-1], "source": "openalex",
                    "url": w.get("doi") or w["id"], "title": " ".join((w.get("title") or "").split()),
                    "abstract": " ".join(slots[i] for i in sorted(slots)),
                    "authors": ", ".join((a.get("author") or {}).get("display_name", "")
                                         for a in (w.get("authorships") or [])[:6])[:200],
                    "published": (w.get("publication_date") or "")[:10],
                    "cited": w.get("cited_by_count") or 0, "hint": domain})
    return out


# ------------------------------------------------------------------ scoring
def _covered() -> list:
    """Token sets of everything the colony has already proposed or concluded: novelty is measured here."""
    sets = [tokens(p["topic"] + " " + (p.get("hypothesis") or "")) for p in store.research_proposals(limit=200)]
    sets += [tokens(n["text"]) for n in store.notes(100)]
    return sets


def score(paper: dict, covered: list, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    text = paper["title"] + ". " + paper["abstract"]
    tk = tokens(text)
    try:
        age = max(0, (today - dt.date.fromisoformat(paper["published"])).days)
    except ValueError:
        age = WINDOW_DAYS
    recency = 0.5 ** (age / 21.0)
    open_hits = sorted({m.group(0).lower() for m in OPEN_QUESTION.finditer(text)})
    test_hits = sorted({m.group(0).lower() for m in TESTABLE.finditer(text)})
    fit = {d: len(tk & tokens(v["vocab"])) for d, v in DOMAINS.items()}
    domains = [d for d, n in sorted(fit.items(), key=lambda kv: -kv[1]) if n >= 2][:2]
    if paper.get("hint") and paper["hint"] not in domains and fit.get(paper["hint"], 0) >= 1:
        domains.append(paper["hint"])
    sim = max((jaccard(tk, c) for c in covered), default=0.0)
    novelty = 1.0 - min(1.0, sim * 3)
    s = (1.2 * recency + 0.35 * min(3, len(open_hits)) + 0.25 * min(3, len(test_hits))
         + 0.3 * max(fit.values()) ** 0.5 / 3 + (0.4 if len(domains) > 1 else 0.0)
         + 0.8 * novelty + 0.1 * math.log1p(paper.get("cited", 0)))
    signals = []
    if DULL.search(paper["title"]) or DULL.search(paper["abstract"][:300]):
        s *= 0.35
        signals.append("survey/position (down-weighted)")
    if open_hits:
        signals.append("open question: " + ", ".join(open_hits[:3]))
    if test_hits:
        signals.append("testable: " + ", ".join(test_hits[:3]))
    if len(domains) > 1:
        signals.append("cross-domain: " + " + ".join(domains))
    signals.append("age %dd, novelty %.2f" % (age, novelty))
    if not domains and paper["source"] == "arxiv":
        domains = [paper["hint"]]           # arXiv was queried by that domain's categories
    return {"score": round(s, 3), "domains": domains,
            "signals": signals}


def refresh(force: bool = False, fetchers=None) -> dict:
    """Fetch the latest papers for every domain, score them, store them. Network errors are per-source."""
    last = float(store.kv_get("frontier_refreshed", "0"))
    if not force and time.time() - last < REFRESH_EVERY:
        return {"skipped": True, "papers": store.frontier_count()}
    since = dt.date.today() - dt.timedelta(days=WINDOW_DAYS)
    covered = _covered()
    seen, titles, papers, errors = set(), set(), [], []
    for domain in DOMAINS:
        for fetch in (fetchers or (_arxiv, _openalex)):
            try:
                batch = fetch(domain, since)
            except (urllib.error.URLError, OSError, ET.ParseError, ValueError) as exc:
                errors.append("%s/%s: %s" % (fetch.__name__.strip("_"), domain, exc))
                continue
            for p in batch:
                norm = re.sub(r"\W+", " ", p["title"].lower()).strip()
                if p["id"] in seen or norm in titles or len(p["abstract"]) < 200:
                    continue
                scored = score(p, covered)
                if p["source"] == "openalex" and len(scored["domains"]) == 0:
                    continue                  # keyword search is loose; keep only what fits a colony domain
                seen.add(p["id"]); titles.add(norm)
                papers.append({**p, **scored})
            time.sleep(3.2 if fetch is _arxiv and fetchers is None else 0)   # arXiv asks for 1 request / 3 s
    fresh = store.save_frontier(papers) if papers else 0
    if papers:
        store.kv_set("frontier_refreshed", str(time.time()))
    return {"fetched": len(papers), "new": fresh, "errors": errors, "papers": store.frontier_count()}


def for_domain(domain: str, limit: int = 3) -> list:
    """What a resident is shown: compact, with the id they must cite."""
    return [{"id": p["id"], "title": p["title"][:140], "published": p["published"],
             "why_it_matters": "; ".join(p["signals"][:3]),
             "abstract": p["abstract"][:380]} for p in store.frontier_for(domain, limit)]


# ------------------------------------------------------------------ the proposal gate
def check_proposal(kind: str, topic: str, hypothesis: str, test: str, paper: str, builds_on: str,
                   proposer: str) -> tuple[dict | None, str]:
    """Return (brief, "") if a research proposal is novel and testable, else (None, why not).

    Builds are exempt: they are engineering, not claims. A research proposal must stand on a
    paper in the frontier pool or on a finding another resident produced, say what would be
    false if the idea is wrong, name something Quorum can run, and not repeat earlier work.
    """
    if kind == "build":
        return {"paper": None, "hypothesis": None, "test": None, "builds_on": None}, ""
    paper, builds_on = (paper or "").strip(), str(builds_on or "").strip().lstrip("#")
    known = store.frontier_paper(paper) if paper else None
    parent = None
    if builds_on.isdigit():
        parent = store.research_proposal(int(builds_on))
        if not parent or parent["status"] != "done":
            parent = None
    if not known and not parent:
        return None, ("cite a paper from `frontier` by its id (`paper`), or a finished colony result via "
                      "`builds_on` (a proposal number from `colleagues`); unsourced questions are not novel research")
    if len(hypothesis or "") < 25:
        return None, "state a falsifiable `hypothesis`: what you expect to find, and what would show you wrong"
    if len(test or "") < 20:
        return None, "give a concrete `test` Quorum can run (a simulation, computation or reproduction)"
    mine = tokens(topic + " " + hypothesis)
    for prior in _covered():
        if jaccard(mine, prior) > 0.5:
            return None, "this repeats work the colony already did or proposed; take a different angle on the paper"
    return {"paper": known["id"] if known else None, "hypothesis": hypothesis, "test": test,
            "builds_on": str(parent["id"]) if parent else None}, ""


def quorum_topic(prop: dict) -> str:
    """The brief Quorum receives (its API caps a topic at 500 chars): novelty first, then the evidence to use."""
    if prop["kind"] == "build" or not prop.get("hypothesis"):
        return prop["topic"][:500]
    paper = store.frontier_paper(prop["paper"]) if prop.get("paper") else None
    parent = store.research_proposal(int(prop["builds_on"])) if (prop.get("builds_on") or "").isdigit() else None
    src = ("Extends %s \"%s\"" % (paper["id"], paper["title"][:90])) if paper else \
          ("Builds on colony result #%s (%s)" % (parent["id"], (parent.get("verdict") or "")[:30]))
    head = "NOVEL: not a textbook derivation. "
    body = "%s. Question: %s Hypothesis: %s Test: %s " % (src, prop["topic"], prop["hypothesis"], prop["test"])
    tail = "Report what is new, what the run confirmed, and what failed."
    room = 500 - len(head) - len(tail)
    return (head + body[:room] + tail)[:500]
