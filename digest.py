"""PDF digests for Creator, delivered to his Telegram through the Hermes bot.

Two reports, both real PDFs (rendered by the machine's own Chrome, no new dependency):

    research  one finished Quorum engagement: the question, the paper it cites, the hypothesis,
              the verdict and the full paper Quorum wrote. Sent once, when the engagement closes.
    daily     what happened in Pantheon since the last one: proposals and their state, what the
              residents found, the frontier papers they are reading, and what needs his decision.

The bot token and chat come from Hermes' own env file (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_HOME_CHANNEL`); they are read at send time and never logged or stored here.
`MIST_DIGEST=0` turns every send off (PDFs are still built on demand by /api/digest/preview).
"""
from __future__ import annotations

import html
import json
import os
import pathlib
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

import store

HERMES_ENV = pathlib.Path.home() / ".hermes" / ".env"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = pathlib.Path(__file__).resolve().parent / "data" / "digests"
QUORUM_REPO = pathlib.Path.home() / "Code" / "quorum"
DAILY_EVERY = 24 * 3600


def enabled() -> bool:
    return os.environ.get("MIST_DIGEST", "1") != "0"


# ------------------------------------------------------------------ markdown -> html (small, enough for papers)
def _inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', t)


def md_to_html(md: str) -> str:
    out, para, items, code, table = [], [], [], None, []

    def flush():
        nonlocal para, items, table
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para)))
        if items:
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % _inline(i) for i in items))
        if table:
            rows = [r for r in table if not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", r)]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            if cells:
                head, body = cells[0], cells[1:]
                out.append("<table><tr>%s</tr>%s</table>" % (
                    "".join("<th>%s</th>" % _inline(c) for c in head),
                    "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c) for c in r) for r in body)))
        para, items, table = [], [], []

    for line in md.splitlines():
        if line.strip().startswith("```"):
            if code is None:
                flush(); code = []
            else:
                out.append("<pre>%s</pre>" % html.escape("\n".join(code))); code = None
            continue
        if code is not None:
            code.append(line); continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush(); n = len(m.group(1)); out.append("<h%d>%s</h%d>" % (n, _inline(m.group(2)), n))
        elif re.match(r"^\s*[-*]\s+", line) or re.match(r"^\s*\d+[.)]\s+", line):
            if para: flush()
            items.append(re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line))
        elif line.strip().startswith("|"):
            if para or items: flush()
            table.append(line)
        elif not line.strip():
            flush()
        else:
            if items or table: flush()
            para.append(line.strip())
    flush()
    return "\n".join(out)


CSS = """
@page { size: A4; margin: 18mm 16mm }
body { font: 10.5pt/1.5 -apple-system, "Helvetica Neue", Arial, sans-serif; color: #1c1f26 }
h1 { font-size: 21pt; margin: 0 0 4pt } h2 { font-size: 14pt; margin: 18pt 0 4pt; border-bottom: 1px solid #d5d9e0; padding-bottom: 2pt }
h3 { font-size: 11.5pt; margin: 12pt 0 2pt } .meta { color: #5d6572; font-size: 9pt; margin-bottom: 10pt }
.card { border: 1px solid #d5d9e0; border-radius: 6px; padding: 8pt 10pt; margin: 6pt 0; page-break-inside: avoid }
.tag { display: inline-block; font-size: 8pt; padding: 1pt 6pt; border-radius: 8pt; background: #e8edf7; color: #2a4a8a; margin-right: 4pt }
.ok { background: #dff3e4; color: #1f6b34 } .bad { background: #fbe3e1; color: #9a2b22 } .wait { background: #fdf0d3; color: #8a5a00 }
code, pre { font: 9pt Menlo, monospace; background: #f3f5f8 } pre { padding: 6pt; white-space: pre-wrap; border-radius: 4px }
table { border-collapse: collapse; margin: 6pt 0; font-size: 9.5pt } td, th { border: 1px solid #d5d9e0; padding: 3pt 6pt; text-align: left }
a { color: #2a4a8a } p { margin: 5pt 0 }
"""


def _page(title: str, meta: str, body: str) -> str:
    return ("<!doctype html><meta charset=utf-8><title>%s</title><style>%s</style><h1>%s</h1>"
            "<div class=meta>%s</div>%s" % (html.escape(title), CSS, html.escape(title), html.escape(meta), body))


def render_pdf(page_html: str, name: str) -> pathlib.Path:
    OUT.mkdir(parents=True, exist_ok=True)
    pdf = OUT / ("%s-%s.pdf" % (name, time.strftime("%Y%m%d-%H%M%S")))
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "report.html"
        src.write_text(page_html, encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                        "--user-data-dir=" + str(pathlib.Path(tmp) / "profile"),
                        "--print-to-pdf=" + str(pdf), src.as_uri()],
                       check=True, capture_output=True, timeout=90)
    if not pdf.is_file() or pdf.stat().st_size < 1000:
        raise RuntimeError("Chrome produced no PDF")
    return pdf


# ------------------------------------------------------------------ reports
def _paper_markdown(path: str | None) -> str:
    if not path:
        return ""
    p = pathlib.Path(path)
    p = p if p.is_absolute() else QUORUM_REPO / p
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def _stamp(ts) -> str:
    return time.strftime("%d %b %Y %H:%M", time.localtime(ts)) if ts else "-"


def _verdict_class(v: str | None) -> str:
    v = (v or "").lower()
    return "ok" if any(w in v for w in ("support", "confirm", "verified", "accept", "pass")) else \
           "bad" if any(w in v for w in ("refut", "fail", "reject", "unsupport")) else "wait"


def research_report(prop: dict) -> tuple[str, str]:
    paper = store.frontier_paper(prop["paper"]) if prop.get("paper") else None
    parent = store.research_proposal(int(prop["builds_on"])) if (prop.get("builds_on") or "").isdigit() else None
    src = ""
    if paper:
        src = ("<div class=card><b>Built on</b><br>%s<br><span class=meta>%s · %s · <a href=\"%s\">%s</a></span>"
               "<p>%s</p></div>" % (html.escape(paper["title"]), html.escape(paper["authors"][:120]),
                                    html.escape(paper["published"]), html.escape(paper["url"]),
                                    html.escape(paper["id"]), html.escape(paper["abstract"][:700])))
    if parent:
        src += ("<div class=card><b>Context passed on from colleague result #%s</b><br>%s</div>" %
                (parent["id"], html.escape(((parent.get("summary") or parent["topic"]))[:600])))
    body = (
        "<p><span class='tag %s'>%s</span><span class=tag>%s</span><span class=tag>proposed by %s</span></p>"
        "<h2>Question</h2><p>%s</p><h2>Hypothesis</h2><p>%s</p><h2>Test</h2><p>%s</p>%s"
        "<h2>Quorum's paper</h2>%s" % (
            _verdict_class(prop.get("verdict")), html.escape(prop.get("verdict") or "no verdict"),
            html.escape(prop["kind"]), html.escape(prop["name"]), html.escape(prop["topic"]),
            html.escape(prop.get("hypothesis") or "(none stated)"), html.escape(prop.get("test") or "(none stated)"),
            src, md_to_html(_paper_markdown(prop.get("paper_path"))) or "<p><i>The paper file was not found.</i></p>"))
    return ("MIST research #%d: %s" % (prop["id"], prop["topic"][:70]),
            _page("Research result #%d" % prop["id"],
                  "Proposed %s · decided %s · %s" % (_stamp(prop["ts"]), _stamp(prop.get("decided")), prop["name"]), body))


def daily_report(since: float) -> tuple[str, str]:
    props = [p for p in store.research_proposals(limit=60) if max(p["ts"], p.get("decided") or 0) >= since]
    pending = store.research_proposals("pending", 20)
    done = [p for p in props if p["status"] == "done"]
    cards = lambda rows: "".join(                                                         # noqa: E731
        "<div class=card><span class='tag %s'>%s</span><span class=tag>%s</span> <b>%s</b><br>%s<br>"
        "<span class=meta>%s</span></div>" % (
            _verdict_class(p.get("verdict")) if p["status"] == "done" else "wait", html.escape(p["status"]),
            html.escape(p["kind"]), html.escape(p["name"]), html.escape(p["topic"][:300]),
            html.escape(("Hypothesis: " + p["hypothesis"][:260]) if p.get("hypothesis") else "")) for p in rows)
    findings = "".join("<li><b>%s</b>: %s</li>" % (html.escape(n["author"]), html.escape(n["text"][:420]))
                       for n in store.notes(10) if n["ts"] >= since)
    reading = "".join(
        "<div class=card><b>%s</b><br><span class=meta>%s · %s</span><br><span class=meta>%s</span></div>" % (
            html.escape(p["title"]), html.escape(p["id"]), html.escape(p["published"]),
            html.escape("; ".join(p["signals"][:3]))) for p in store.frontier_for(None, 5, unused=False))
    body = ("<h2>Needs your decision (%d)</h2>%s<h2>Finished (%d)</h2>%s<h2>What the residents found</h2><ul>%s</ul>"
            "<h2>Proposals this period</h2>%s<h2>Top of the research frontier</h2>%s" % (
                len(pending), cards(pending) or "<p>Nothing waiting.</p>", len(done), cards(done) or "<p>None.</p>",
                findings or "<li>No new findings.</li>", cards([p for p in props if p["status"] not in ("done", "pending")]) or "<p>None.</p>",
                reading or "<p>The scout has not fetched papers yet.</p>"))
    return ("MIST daily digest", _page("MIST daily digest", "Pantheon, since %s" % _stamp(since), body))


# ------------------------------------------------------------------ Telegram
def _hermes_env() -> dict:
    env = {}
    try:
        for line in HERMES_ENV.read_text().splitlines():
            m = re.match(r"^\s*(TELEGRAM_BOT_TOKEN|TELEGRAM_HOME_CHANNEL)\s*=\s*(.*?)\s*$", line)
            if m:
                env[m.group(1)] = m.group(2).strip("'\"")
    except OSError:
        pass
    return env


def send_pdf(pdf: pathlib.Path, caption: str) -> dict:
    env = _hermes_env()
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_HOME_CHANNEL")
    if not token or not chat:
        return {"sent": False, "error": "no Telegram bot token / home channel in %s" % HERMES_ENV}
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", chat), ("caption", caption[:1000])):
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"%s\"\r\n"
                  "Content-Type: application/pdf\r\n\r\n" % (boundary, pdf.name)).encode())
    parts += [pdf.read_bytes(), ("\r\n--%s--\r\n" % boundary).encode()]
    req = urllib.request.Request("https://api.telegram.org/bot%s/sendDocument" % token, data=b"".join(parts),
                                 headers={"content-type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            ok = json.loads(resp.read()).get("ok")
        return {"sent": bool(ok)}
    except urllib.error.HTTPError as exc:
        return {"sent": False, "error": "Telegram HTTP %d" % exc.code}      # the URL carries the token: say nothing more
    except (urllib.error.URLError, OSError) as exc:
        return {"sent": False, "error": "Telegram unreachable (%s)" % type(exc).__name__}


# ------------------------------------------------------------------ triggers
def send_research(pid: int) -> dict:
    """Build and send the PDF for a finished proposal, once."""
    prop = store.research_proposal(pid)
    if not prop or prop["status"] != "done":
        return {"sent": False, "error": "proposal is not finished"}
    if prop.get("digest_sent"):
        return {"sent": False, "error": "already sent"}
    caption, page = research_report(prop)
    pdf = render_pdf(page, "research-%d" % pid)
    if not enabled():
        return {"sent": False, "pdf": str(pdf), "error": "MIST_DIGEST=0"}
    out = send_pdf(pdf, caption + "\nVerdict: " + (prop.get("verdict") or "none"))
    if out.get("sent"):
        store.update_research(pid, digest_sent=time.time())
    return {**out, "pdf": str(pdf)}


def send_pending_research() -> int:
    """Catch up on finished proposals whose PDF has not gone out (e.g. the bot was unreachable)."""
    sent = 0
    for prop in store.research_proposals("done", 20):
        if not prop.get("digest_sent") and enabled():
            try:
                sent += bool(send_research(prop["id"]).get("sent"))
            except (subprocess.SubprocessError, RuntimeError, OSError):
                continue
    return sent


def maybe_daily(now: float | None = None) -> dict | None:
    now = now or time.time()
    last = float(store.kv_get("digest_daily", "0"))
    if not enabled() or now - last < DAILY_EVERY:
        return None
    since = last or now - DAILY_EVERY
    caption, page = daily_report(since)
    pdf = render_pdf(page, "daily")
    out = send_pdf(pdf, caption)
    if out.get("sent"):
        store.kv_set("digest_daily", str(now))
    return {**out, "pdf": str(pdf)}
