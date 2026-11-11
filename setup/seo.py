"""Search, AI-search and indexing for MINTRO's website — run after any page or version change.

    python setup/seo.py                      # refresh docs/ in place: head tags, structured data, facts, llms.txt
    python setup/seo.py --coins              # first rebuild coins.html's coin list from the live catalog
    python setup/seo.py <dir> --sitemap      # the same on a deploy copy, plus sitemap.xml + robots.txt
    python setup/seo.py --indexnow           # after a deploy: tell Bing, Yandex, Seznam, Naver... every page changed

What it keeps right, on every page except the 404 (which stays noindex):
  * canonical, hreflang, og:url and og:image on the real host, https://mintro.aiteleresearch.com — so the
    GitHub Pages copy never competes with it in search;
  * robots (index, follow, full snippets, large image previews), author, application name, og:locale, the
    1200x630 share image with its size and alt text, and the X handle;
  * JSON-LD: the publisher (Aitele Research LLP) and the website on every page, and per page what it is —
    the app itself (SoftwareApplication) and its FAQ on the home page, the install steps (HowTo) on the
    download page, the coin list (ItemList) on the coins page, the guide (Article), the FAQ page (FAQPage),
    with breadcrumbs everywhere but the home page. Questions and steps are read from the pages themselves.
  * facts on the pages: the current version and installer size wherever a page marks them (data-seo).
  * llms.txt and llms-full.txt: what MINTRO is, for AI assistants and answer engines (llmstxt.org).
  * the IndexNow key file, so --indexnow submissions are accepted.
With --sitemap it also writes sitemap.xml (each page's last change from git, priority, change frequency,
the share image) and robots.txt (every crawler, search and AI alike, may read the pages; not /api,
/download or /v1). Idempotent: running it twice changes nothing the second time.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser

SITE = "https://mintro.aiteleresearch.com"
HOST = "mintro.aiteleresearch.com"
OLD_HOST = "https://aiteleresearch.github.io/mintro"
ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "mintro" / "__init__.py").read_text("utf-8")).group(1)
# A JPEG: WhatsApp drops a link preview whose image is over ~300 KB, and the PNG (assets/og.png) is 324 KB.
IMAGE = f"{SITE}/assets/og.jpg"
IMAGE_ALT = "MINTRO: a mint crystal with a basket of coins in orbit, and the words Early coins. Ordinary laptop. Three clicks."
# IndexNow (indexnow.org): the key is public by design; the file of the same name proves the site is ours.
INDEXNOW_KEY = "4d6322414e141882b445ae4b9da4763a"
GUIDE_PUBLISHED = "2026-11-10"

# page → (path on the site, crumb name, kind, sitemap priority, change frequency)
PAGES = {
    "index.html": ("/", "MINTRO", "WebPage", "1.0", "weekly"),
    "download.html": ("/download.html", "Download", "Download", "0.9", "weekly"),
    "coins.html": ("/coins.html", "Coins you can mine", "Coins", "0.8", "daily"),
    "mine-crypto-on-a-laptop.html": ("/mine-crypto-on-a-laptop.html", "Mining crypto on a laptop", "Article", "0.8", "monthly"),
    "faq.html": ("/faq.html", "FAQ", "FAQPage", "0.8", "monthly"),
    "contact.html": ("/contact.html", "Contact", "ContactPage", "0.6", "monthly"),
    "risk.html": ("/risk.html", "Risk disclosure", "WebPage", "0.5", "monthly"),
    "terms.html": ("/terms.html", "Terms", "WebPage", "0.3", "yearly"),
    "privacy.html": ("/privacy.html", "Privacy", "WebPage", "0.3", "yearly"),
    "legal.html": ("/legal.html", "Legal notice", "WebPage", "0.3", "yearly"),
}

ORG = {
    "@type": "Organization",
    "@id": "https://aiteleresearch.com/#organization",
    "name": "Aitele Research LLP",
    "url": "https://aiteleresearch.com",
    "logo": "https://aiteleresearch.com/logo.png",
    "email": "hello@aiteleresearch.com",
    "sameAs": [
        "https://www.linkedin.com/company/aitele",
        "https://x.com/aiteleresearch",
        "https://www.instagram.com/aiteleresearch/",
        "https://www.youtube.com/@aiteleresearch",
    ],
}
WEBSITE = {
    "@type": "WebSite",
    "@id": f"{SITE}/#website",
    "url": f"{SITE}/",
    "name": "MINTRO",
    "alternateName": "MINTRO crypto mining app",
    "description": "MINTRO, a free and open-source crypto mining app for Windows laptops and desktops.",
    "inLanguage": "en",
    "publisher": {"@id": ORG["@id"]},
}
FEATURES = [
    "Mines a basket of CPU-mineable coins, sized to what the PC can carry",
    "Auto mode: tuned to the PC, backs off while you work, pauses on battery",
    "One-click wallets for Monero, Zephyr, Salvium and MYT with each coin's official tools",
    "XMRig, cpuminer-opt and SRBMiner-Multi engines, downloaded from their official releases and checksum-checked",
    "Optional GPU mining on discrete NVIDIA, AMD and Intel Arc graphics",
    "Pool fallbacks, payout checks and plain-language self-test",
    "Silent, signed self-updates that never stop mining",
    "Tax report CSV, Windows alerts and a view of all your PCs",
    "No fee: every share goes to your own wallet address",
]
KEYWORDS = ("crypto mining app, crypto miner for Windows, mine crypto on a laptop, CPU mining, free crypto miner, "
            "RandomX miner, Monero mining, XMRig GUI, cpuminer-opt, GhostRider, yespower, mining pool, open source miner")
# Engine algorithm names → what people search for
ALGOS = {"rx/0": "RandomX", "rx/arq": "RandomARQ", "rx/wow": "RandomWOW", "gr": "GhostRider", "yespower": "yespower",
         "yespowerr16": "yespowerR16", "yescryptr32": "yescryptR32", "power2b": "power2b", "minotaurx": "MinotaurX",
         "firopow": "FiroPoW", "meowpow": "MeowPoW"}
ENGINES = {"xmrig": "XMRig", "cpuminer": "cpuminer-opt", "srbminer": "SRBMiner-Multi"}


def text(fragment: str) -> str:
    """Plain text of an HTML fragment."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def meta_content(head: str, attr: str, key: str) -> str | None:
    m = re.search(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)"', head)
    return html.unescape(m.group(1)) if m else None


def set_meta(head: str, attr: str, key: str, value: str, after: str | None = None) -> str:
    tag = f'<meta {attr}="{key}" content="{html.escape(value, quote=True)}">'
    pat = re.compile(rf'<meta {attr}="{re.escape(key)}" content="[^"]*">')
    if pat.search(head):
        return pat.sub(lambda _: tag, head, count=1)
    if after:
        m = re.search(rf'<meta (?:name|property)="{re.escape(after)}" content="[^"]*">', head)
        if m:
            return head[: m.end()] + "\n" + tag + head[m.end():]
    return head.replace("</head>", f"{tag}\n</head>") if "</head>" in head else head + tag + "\n"


def installer_mb() -> int | None:
    exe = ROOT / "dist" / f"MINTRO-Setup-{VERSION}.exe"
    return round(exe.stat().st_size / 1e6) if exe.exists() else None


def faq_items(body: str) -> list[tuple[str, str]]:
    return [(text(q), text(a)) for q, a in
            re.findall(r"<details[^>]*>\s*<summary>(.*?)</summary>\s*<div class=\"ans\">(.*?)</div>\s*</details>", body, re.S)]


def questions(items: list[tuple[str, str]]) -> list[dict]:
    return [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in items]


def breadcrumb(url: str, crumb: str) -> dict:
    return {"@type": "BreadcrumbList", "@id": f"{url}#breadcrumb", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "MINTRO", "item": f"{SITE}/"},
        {"@type": "ListItem", "position": 2, "name": crumb, "item": url},
    ]}


def app_entity(head: str) -> dict:
    app = {
        "@type": "SoftwareApplication",
        "@id": f"{SITE}/#app",
        "name": "MINTRO",
        "alternateName": "MINTRO crypto miner",
        "url": f"{SITE}/",
        "description": meta_content(head, "name", "description") or "",
        "applicationCategory": "FinanceApplication",
        "applicationSubCategory": "Cryptocurrency mining",
        "operatingSystem": "Windows 10, Windows 11 (64-bit)",
        "softwareVersion": VERSION,
        "softwareRequirements": "Windows 10 or 11, 64-bit; Microsoft Edge WebView2 Runtime (built into Windows 11)",
        "memoryRequirements": "About 2.5 GB of free RAM for RandomX coins (others need far less)",
        "processorRequirements": "64-bit x86 processor",
        "downloadUrl": f"{SITE}/download/MINTRO-Setup-{VERSION}.exe",
        "installUrl": f"{SITE}/download.html",
        "releaseNotes": f"{SITE}/download.html#whats-new",
        "featureList": FEATURES,
        "keywords": KEYWORDS,
        "image": IMAGE,
        "screenshot": IMAGE,
        "license": "https://www.gnu.org/licenses/gpl-3.0.html",
        "isAccessibleForFree": True,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD", "availability": "https://schema.org/InStock"},
        "author": {"@id": ORG["@id"]},
        "publisher": {"@id": ORG["@id"]},
        "sameAs": ["https://github.com/aiteleresearch/mintro"],
    }
    if installer_mb():
        app["fileSize"] = f"{installer_mb()} MB"
    return app


def jsonld(page: str, path: str, crumb: str, kind: str, head: str, body: str, modified: str) -> dict:
    url = f"{SITE}{path}"
    graph: list[dict] = [ORG, WEBSITE]
    title = text(re.search(r"<title>(.*?)</title>", head, re.S).group(1))
    webpage = {
        "@type": {"ContactPage": "ContactPage", "FAQPage": "FAQPage", "Coins": "CollectionPage"}.get(kind, "WebPage"),
        "@id": f"{url}#webpage",
        "url": url,
        "name": re.sub(r"\s*·\s*MINTRO$", "", title),
        "description": meta_content(head, "name", "description") or "",
        "isPartOf": {"@id": WEBSITE["@id"]},
        "inLanguage": "en",
        "dateModified": modified,
        "primaryImageOfPage": {"@type": "ImageObject", "url": IMAGE, "width": 1200, "height": 630},
    }
    if page == "index.html":
        webpage["name"] = "MINTRO — free crypto mining app for Windows laptops"
        webpage["about"] = {"@id": f"{SITE}/#app"}
        graph += [webpage, app_entity(head)]
        faqs = faq_items(body)
        if faqs:
            graph.append({"@type": "FAQPage", "@id": f"{SITE}/#faq", "url": f"{SITE}/#faq",
                          "isPartOf": {"@id": f"{SITE}/#webpage"}, "mainEntity": questions(faqs)})
        return {"@context": "https://schema.org", "@graph": graph}

    webpage["breadcrumb"] = {"@id": f"{url}#breadcrumb"}
    graph += [webpage, breadcrumb(url, crumb)]
    if kind == "ContactPage":
        webpage["mainEntity"] = {"@id": ORG["@id"]}
    elif kind == "FAQPage":
        webpage["mainEntity"] = questions(faq_items(body))
        webpage["about"] = {"@id": f"{SITE}/#app"}
    elif kind == "Download":
        webpage["about"] = {"@id": f"{SITE}/#app"}
        graph.append(app_entity(head))
        steps = re.findall(r'<li[^>]*data-step[^>]*>.*?<h3>(.*?)</h3>(.*?)</li>', body, re.S)
        if steps:
            graph.append({
                "@type": "HowTo", "@id": f"{url}#install", "name": "How to install MINTRO on Windows",
                "description": "Download MINTRO, get past Windows' first-run warning, and install it in a few seconds.",
                "totalTime": "PT2M", "tool": [{"@type": "HowToTool", "name": "A Windows 10 or 11 PC"}],
                "step": [{"@type": "HowToStep", "position": i + 1, "name": text(n), "text": text(t), "url": f"{url}#step-{i + 1}"}
                         for i, (n, t) in enumerate(steps)],
            })
    elif kind == "Coins":
        rows = re.findall(r'<tr data-coin="([^"]+)" data-name="([^"]+)"[^>]*data-algo="([^"]+)"', body)
        webpage["mainEntity"] = {"@id": f"{url}#coins"}
        webpage["about"] = {"@id": f"{SITE}/#app"}
        graph.append({
            "@type": "ItemList", "@id": f"{url}#coins", "name": "Coins you can mine with MINTRO",
            "numberOfItems": len(rows), "itemListOrder": "https://schema.org/ItemListOrderAscending",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": f"{html.unescape(n)} ({s})",
                                 "description": f"{html.unescape(n)} ({s}), mined on {html.unescape(a)} with MINTRO"}
                                for i, (s, n, a) in enumerate(rows)],
        })
    elif kind == "Article":
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
        words = len(text(re.search(r"<main.*?</main>", body, re.S).group(0)).split())
        webpage["mainEntity"] = {"@id": f"{url}#article"}
        graph.append({
            "@type": "Article", "@id": f"{url}#article", "headline": text(h1.group(1)) if h1 else webpage["name"],
            "description": webpage["description"], "image": IMAGE, "inLanguage": "en", "wordCount": words,
            "datePublished": GUIDE_PUBLISHED, "dateModified": max(modified, GUIDE_PUBLISHED),
            "author": {"@id": ORG["@id"]}, "publisher": {"@id": ORG["@id"]},
            "mainEntityOfPage": {"@id": f"{url}#webpage"}, "about": [
                {"@type": "Thing", "name": "Cryptocurrency mining"}, {"@type": "Thing", "name": "CPU mining"}],
            "mentions": {"@id": f"{SITE}/#app"},
        })
    return {"@context": "https://schema.org", "@graph": graph}


def set_facts(rest: str) -> str:
    """Keep the version and installer size current wherever a page marks them with data-seo."""
    rest = re.sub(r'(<[^>]+data-seo="version"[^>]*>)[^<]*(<)', lambda m: f"{m.group(1)}{VERSION}{m.group(2)}", rest)
    mb = installer_mb()
    if mb:
        rest = re.sub(r'(<[^>]+data-seo="size"[^>]*>)[^<]*(<)', lambda m: f"{m.group(1)}{mb} MB{m.group(2)}", rest)
    return rest


def refresh(page: str, file: pathlib.Path) -> bool:
    src = file.read_text("utf-8")
    end = src.index("</head>")
    head, rest = src[: end + len("</head>")], src[end + len("</head>"):]
    path, crumb, kind, _, _ = PAGES[page]
    url = f"{SITE}{path}"

    head = head.replace(OLD_HOST + "/", SITE + "/").replace(OLD_HOST, SITE)
    head = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', head)
    head = re.sub(r'\n<link rel="alternate" hreflang="[^"]*" href="[^"]*">', "", head)
    head = head.replace(f'<link rel="canonical" href="{url}">',
                        f'<link rel="canonical" href="{url}">\n<link rel="alternate" hreflang="en" href="{url}">'
                        f'\n<link rel="alternate" hreflang="x-default" href="{url}">', 1)
    head = set_meta(head, "name", "robots", "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1", after="theme-color")
    head = set_meta(head, "name", "author", "Aitele Research LLP", after="robots")
    head = set_meta(head, "name", "application-name", "MINTRO", after="author")
    head = set_meta(head, "name", "apple-mobile-web-app-title", "MINTRO", after="application-name")
    head = set_meta(head, "property", "og:url", url, after="og:site_name")
    head = set_meta(head, "property", "og:locale", "en_US", after="og:site_name")
    head = set_meta(head, "property", "og:image", IMAGE, after="og:description")
    head = set_meta(head, "property", "og:image:type", "image/jpeg", after="og:image")
    head = set_meta(head, "property", "og:image:width", "1200", after="og:image:type")
    head = set_meta(head, "property", "og:image:height", "630", after="og:image:width")
    head = set_meta(head, "property", "og:image:alt", IMAGE_ALT, after="og:image:height")
    head = set_meta(head, "name", "twitter:site", "@aiteleresearch", after="twitter:card")
    head = set_meta(head, "name", "twitter:creator", "@aiteleresearch", after="twitter:site")
    for k in ("title", "description"):
        v = meta_content(head, "property", f"og:{k}")
        if v:
            head = set_meta(head, "name", f"twitter:{k}", v, after="twitter:creator")
    head = set_meta(head, "name", "twitter:image", IMAGE, after="twitter:description")
    head = set_meta(head, "name", "twitter:image:alt", IMAGE_ALT, after="twitter:image")
    if kind == "Article":
        head = set_meta(head, "property", "article:published_time", GUIDE_PUBLISHED, after="og:image:alt")
        head = set_meta(head, "property", "article:modified_time", max(last_change(page), GUIDE_PUBLISHED), after="article:published_time")

    rest = set_facts(rest)
    ld = json.dumps(jsonld(page, path, crumb, kind, head, rest, last_change(page)), ensure_ascii=False, indent=1)
    block = f'<script type="application/ld+json" id="mintro-ld">\n{ld}\n</script>'
    if 'id="mintro-ld"' in head:
        head = re.sub(r'<script type="application/ld\+json" id="mintro-ld">.*?</script>', lambda _: block, head, count=1, flags=re.S)
    else:
        head = head.replace("</head>", f"{block}\n</head>")

    out = head + rest
    if out != src:
        file.write_text(out, "utf-8", newline="")
        return True
    return False


def last_change(page: str) -> str:
    try:
        d = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%cs", "--", f"docs/{page}"],
                           capture_output=True, text=True, timeout=20).stdout.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            return d
    except (OSError, subprocess.SubprocessError):
        pass
    f = ROOT / "docs" / page
    return dt.date.fromtimestamp(f.stat().st_mtime).isoformat() if f.exists() else dt.date.today().isoformat()


# ---- the coins page, from the same catalog the app mines ----------------------------------------------------

def build_coins(file: pathlib.Path) -> int:
    """Rewrite the coin table in coins.html from the live catalog (rplant's coins MINTRO's engines can mine,
    plus listed coins). Returns how many coins it lists."""
    sys.path.insert(0, str(ROOT))
    from mintro import coins as catalog, wallets
    data = catalog.get(force=True)
    if data.get("stale"):
        raise SystemExit(f"seo: the coin catalog is offline ({data.get('error')}); coins.html left as it was")
    rows = []
    for sym, c in sorted(data["coins"].items(), key=lambda kv: (kv[1].get("lane") != "cpu", kv[1]["name"].lower())):
        algo = ALGOS.get(c.get("algo"), c.get("algo") or "")
        markets = len(c.get("markets") or c.get("exchanges") or [])
        links = c.get("links") or {}
        link = " ".join(f'<a href="{html.escape(links[k])}" target="_blank" rel="nofollow noopener">{label}</a>'
                        for k, label in (("site", "Website"), ("be", "Explorer")) if str(links.get(k, "")).startswith("https://"))
        tags = []
        if sym in wallets.SOURCES:
            tags.append('<span class="tag">one-click wallet</span>')
        if c.get("listing"):
            tags.append('<span class="tag gold">listed</span>')
        rows.append(
            f'      <tr data-coin="{html.escape(sym)}" data-name="{html.escape(c["name"])}" data-algo="{html.escape(algo)}">\n'
            f'        <th scope="row"><b>{html.escape(c["name"])}</b> <span class="sym">{html.escape(sym)}</span>{"".join(tags)}</th>\n'
            f'        <td>{html.escape(algo)}</td><td>{"GPU" if c.get("lane") == "gpu" else "CPU"}</td>'
            f'<td>{ENGINES.get(c.get("engine"), c.get("engine") or "")}</td>\n'
            f'        <td>{round(c["block_time"] / 60, 1):g} min</td>'
            f'<td>{f"{markets} exchange" + ("s" if markets > 1 else "") if markets else "No market yet"}</td>\n'
            f'        <td class="links" data-md="skip">{link}</td>\n      </tr>')
    src = file.read_text("utf-8")
    table = "<!-- coins:start -->\n" + "\n".join(rows) + "\n      <!-- coins:end -->"
    out = re.sub(r"<!-- coins:start -->.*?<!-- coins:end -->", lambda _: table, src, count=1, flags=re.S)
    today = dt.date.today()
    out = re.sub(r'(<[^>]+data-seo="coins-date"[^>]*>)[^<]*(<)', lambda m: f"{m.group(1)}{today.day} {today:%B %Y}{m.group(2)}", out)
    out = re.sub(r'(<[^>]+data-seo="coins-count"[^>]*>)[^<]*(<)', lambda m: f"{m.group(1)}{len(rows)}{m.group(2)}", out)
    file.write_text(out, "utf-8", newline="")
    return len(rows)


# ---- llms.txt: MINTRO for AI assistants and answer engines --------------------------------------------------

class _Markdown(HTMLParser):
    """The readable content of a page's <main> as Markdown: headings, paragraphs, lists, questions, tables."""
    SKIP = {"script", "style", "svg", "noscript", "button", "dialog", "figure", "form", "select", "template"}
    VOID = {"br", "img", "input", "meta", "link", "hr", "wbr", "source", "area", "col", "embed", "param", "track",
            "path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "stop", "use"}
    BLOCK = {"p": "", "li": "- ", "h1": "# ", "h2": "## ", "h3": "### ", "summary": "### ", "tr": "- ", "dt": "- ", "dd": "  ",
             "div": "", "section": "", "header": "", "article": "", "nav": ""}
    INLINE = {"b", "strong", "em", "i", "code", "q", "sup", "sub", "time", "abbr", "kbd", "u", "mark"}
    # demos and placeholders that mean nothing as text: the numbering beside a section, the example basket, live counters
    SKIP_CLASSES = {"c-idx", "scores", "nums", "ticker", "dl-stat", "dl-hero", "toc", "legal-more", "sec-more", "honest-more"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.buf, self.skip, self.depth, self.inside, self.href = [], [], 0, 0, False, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main":
            self.inside = True
        if not self.inside:
            return
        classes = set((a.get("class") or "").split())
        if (self.skip or tag in self.SKIP or a.get("aria-hidden") == "true" or "hidden" in a or a.get("data-md") == "skip"
                or a.get("role") == "img" or classes & self.SKIP_CLASSES):
            if tag not in self.VOID:
                self.skip += 1
            return
        if tag in self.BLOCK:
            self.flush()
            self.buf.append(self.BLOCK[tag])
        elif tag in ("td", "th") and "".join(self.buf).strip() not in ("", "-"):
            self.buf.append(" · ")
        elif tag not in self.INLINE:
            self.buf.append(" ")  # a box ends a word: <span>01</span><small>Choosing</small> is "01 Choosing"
        if tag == "a":
            self.href = a.get("href")

    def handle_endtag(self, tag):
        if not self.inside:
            return
        if self.skip:
            if tag not in self.VOID:
                self.skip -= 1
            return
        if tag == "main":
            self.flush()
            self.inside = False
        elif tag in self.BLOCK:
            self.flush()
        elif tag not in self.INLINE:
            self.buf.append(" ")
        if tag == "a":
            self.href = None

    def handle_data(self, data):
        if self.inside and not self.skip:
            self.buf.append(re.sub(r"\s+", " ", data))

    def flush(self):
        line = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if line and line not in ("-", "#", "##", "###"):
            self.out.append(line)

    def markdown(self) -> str:
        self.flush()
        lines, prev = [], None
        for line in self.out:
            if line != prev:
                lines.append(line)
            prev = line
        md = []
        for line in lines:
            if line.startswith("#") and md and md[-1] != "":
                md.append("")
            md.append(line)
            if line.startswith("#"):
                md.append("")
        return re.sub(r"\n{3,}", "\n\n", "\n".join(md)).strip()


def page_markdown(file: pathlib.Path) -> str:
    p = _Markdown()
    p.feed(file.read_text("utf-8"))
    return p.markdown()


def write_llms(out: pathlib.Path) -> None:
    pages = []
    for page, (path, crumb, _, _, _) in PAGES.items():
        f = out / page
        if f.exists():
            head = f.read_text("utf-8").split("</head>", 1)[0]
            title = re.sub(r"\s*·\s*MINTRO$", "", text(re.search(r"<title>(.*?)</title>", head, re.S).group(1)))
            pages.append((page, path, title, meta_content(head, "name", "description") or ""))
    first = [p for p in pages if p[0] not in ("terms.html", "privacy.html", "legal.html", "contact.html")]
    rest = [p for p in pages if p not in first]
    summary = [
        "# MINTRO",
        "",
        "> MINTRO is a free, open-source (GPL-3.0) crypto mining app for Windows 10 and 11. It floats on the desktop as a "
        "small card, mines a basket of early-stage CPU-mineable coins on an ordinary laptop or desktop, tunes itself to the "
        "PC, and pays every share straight to the user's own wallets. MINTRO takes no fee.",
        "",
        f"- Current version: {VERSION}, for Windows 10 and 11 (64-bit); installs per user, no admin rights.",
        "- Engines: XMRig (RandomX, RandomARQ, RandomWOW, GhostRider), cpuminer-opt (yespower, yespowerR16, yescryptR32, "
        "power2b, MinotaurX) and, on PCs with a discrete GPU, SRBMiner-Multi (FiroPoW, MeowPoW).",
        "- Coins: the CPU coins on the rplant pool those engines can mine (Monero, Zephyr, Salvium, Raptoreum and newer "
        "coins with no market yet), plus coins listed by their projects. The basket only keeps coins that reach the "
        "pool's minimum payout within a week on that PC.",
        "- Wallets: one-click wallets for Monero, Zephyr, Salvium and MYT made with each coin's official tools, or paste "
        "any address. MINTRO never holds anyone's coins.",
        "- Earnings: small. A laptop mines cents' worth a day, and most new coins never gain value: MINTRO is a way to "
        "hold a little of several early coins, not an income. Not financial advice.",
        "- Who makes it: Aitele Research LLP. Source code: https://github.com/aiteleresearch/mintro",
        "",
        "## Pages",
        "",
        *[f"- [{t}]({SITE}{p}): {d}" for _, p, t, d in first],
        "",
        "## Optional",
        "",
        *[f"- [{t}]({SITE}{p}): {d}" for _, p, t, d in rest],
        f"- [Source code on GitHub](https://github.com/aiteleresearch/mintro): the app, the website and the release tools.",
        f"- [Full text of this site]({SITE}/llms-full.txt): every page above as plain Markdown.",
    ]
    (out / "llms.txt").write_text("\n".join(summary) + "\n", "utf-8", newline="\n")
    full = ["# MINTRO: the full website as text", "", f"Source: {SITE}/ · Version {VERSION} · Generated from the live pages.", ""]
    for page, path, title, desc in pages:
        full += ["", "---", "", f"URL: {SITE}{path}", "", page_markdown(out / page)]
    (out / "llms-full.txt").write_text(re.sub(r"\n{3,}", "\n\n", "\n".join(full)).strip() + "\n", "utf-8", newline="\n")


# ---- sitemap, robots and IndexNow -----------------------------------------------------------------------

AI_AGENTS = ["Googlebot", "Bingbot", "Applebot", "DuckDuckBot", "YandexBot", "Google-Extended", "Applebot-Extended",
             "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot",
             "Perplexity-User", "CCBot", "Amazonbot", "meta-externalagent", "MistralAI-User", "cohere-ai"]
PRIVATE = ["/api/", "/download/", "/v1/"]


def write_sitemap(out: pathlib.Path) -> None:
    rows = []
    for page, (path, _, _, prio, freq) in PAGES.items():
        if not (out / page).exists():
            continue
        img = f"\n    <image:image><image:loc>{IMAGE}</image:loc></image:image>" if page == "index.html" else ""
        rows.append(
            f"  <url>\n    <loc>{SITE}{path}</loc>\n    <lastmod>{last_change(page)}</lastmod>\n"
            f"    <changefreq>{freq}</changefreq>\n    <priority>{prio}</priority>{img}\n  </url>"
        )
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n' + "\n".join(rows) + "\n</urlset>\n",
        "utf-8", newline="\n")
    rules = "".join(f"Disallow: {p}\n" for p in PRIVATE)
    (out / "robots.txt").write_text(
        "# MINTRO's website. Search engines and AI assistants are welcome to read, index and cite every page.\n"
        f"# A summary for AI assistants: {SITE}/llms.txt\n\n"
        f"User-agent: *\nAllow: /\n{rules}\n"
        "# Named so a rule written for one of them elsewhere can't shut it out by accident\n"
        + "".join(f"User-agent: {a}\n" for a in AI_AGENTS) + f"Allow: /\n{rules}\n"
        f"Sitemap: {SITE}/sitemap.xml\n", "utf-8", newline="\n")


def write_indexnow_key(out: pathlib.Path) -> None:
    (out / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY, "utf-8", newline="")


def submit_indexnow() -> int:
    """Tell IndexNow (Bing, Yandex, Seznam, Naver, Yep...) that every page may have changed. Run after a deploy."""
    urls = [f"{SITE}{path}" for page, (path, *_) in PAGES.items() if (ROOT / "docs" / page).exists()]
    urls += [f"{SITE}/llms.txt", f"{SITE}/llms-full.txt"]
    body = json.dumps({"host": HOST, "key": INDEXNOW_KEY, "keyLocation": f"{SITE}/{INDEXNOW_KEY}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"seo: IndexNow accepted {len(urls)} URLs (HTTP {r.status})")
            return 0
    except urllib.error.HTTPError as e:
        why = {403: "the key file isn't live yet: deploy first", 422: "a URL isn't on the key's host",
               429: "too many submissions: try again later"}.get(e.code, e.reason)
        print(f"seo: IndexNow refused the submission (HTTP {e.code}: {why})")
    except OSError as e:
        print(f"seo: couldn't reach IndexNow ({e})")
    return 1


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--indexnow" in sys.argv:
        return submit_indexnow()
    target = pathlib.Path(args[0]) if args else ROOT / "docs"
    if "--coins" in sys.argv:
        print(f"seo: coins.html lists {build_coins(target / 'coins.html')} coins")
    changed = [p for p in PAGES if (target / p).exists() and refresh(p, target / p)]
    print(f"seo: {len(changed)} page(s) updated in {target} (MINTRO {VERSION})")
    write_llms(target)
    write_indexnow_key(target)
    print("seo: llms.txt, llms-full.txt and the IndexNow key written")
    if "--sitemap" in sys.argv:
        write_sitemap(target)
        print(f"seo: sitemap.xml + robots.txt written for {SITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
