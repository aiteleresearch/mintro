"""Search metadata for MINTRO's website — run after any page or version change.

    python setup/seo.py                      # refresh docs/ in place (head tags + structured data)
    python setup/seo.py <dir> --sitemap      # the same on a deploy copy, plus sitemap.xml + robots.txt

What it keeps right, on every page except the 404 (which stays noindex):
  * canonical, og:url and og:image on the real host, https://mintro.aiteleresearch.com — so the
    GitHub Pages copy never competes with it in search;
  * robots (index, follow, large image previews), author, application name, og:locale, the
    1200x630 share image with its size and alt text, and the X handle;
  * JSON-LD: the publisher (Aitele Research LLP) and the website on every page; on the home page
    the app itself (SoftwareApplication: Windows, free, GPL-3.0, current version and installer)
    and the FAQ, read from the page's own <details>; a breadcrumb on every other page.
With --sitemap it also writes sitemap.xml (each page's last change from git, priority and change
frequency, the share image) and robots.txt (crawl the pages, not /api, /download or /v1).
Idempotent: running it twice changes nothing the second time.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
import re
import subprocess
import sys

SITE = "https://mintro.aiteleresearch.com"
OLD_HOST = "https://aiteleresearch.github.io/mintro"
ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "mintro" / "__init__.py").read_text("utf-8")).group(1)
IMAGE = f"{SITE}/assets/og.png"
IMAGE_ALT = "MINTRO: a mint crystal with a basket of coins in orbit, and the words Early coins. Ordinary laptop. Three clicks."

# page → (path on the site, crumb name, schema type, sitemap priority, change frequency)
PAGES = {
    "index.html": ("/", "MINTRO", "WebPage", "1.0", "weekly"),
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
    "inLanguage": "en",
    "publisher": {"@id": ORG["@id"]},
}


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


def jsonld(page: str, path: str, crumb: str, kind: str, head: str, body: str) -> dict:
    url = f"{SITE}{path}"
    graph: list[dict] = [ORG, WEBSITE]
    webpage = {
        "@type": kind,
        "@id": f"{url}#webpage",
        "url": url,
        "name": re.sub(r"\s*·\s*MINTRO$", "", text(re.search(r"<title>(.*?)</title>", head, re.S).group(1))),
        "description": meta_content(head, "name", "description") or "",
        "isPartOf": {"@id": WEBSITE["@id"]},
        "inLanguage": "en",
        "primaryImageOfPage": {"@type": "ImageObject", "url": IMAGE, "width": 1200, "height": 630},
    }
    if page == "index.html":
        webpage["name"] = "MINTRO — mine a basket of early coins on an ordinary laptop"
        webpage["about"] = {"@id": f"{SITE}/#app"}
        graph.append(webpage)
        graph.append({
            "@type": "SoftwareApplication",
            "@id": f"{SITE}/#app",
            "name": "MINTRO",
            "url": f"{SITE}/",
            "description": meta_content(head, "name", "description") or "",
            "applicationCategory": "UtilitiesApplication",
            "applicationSubCategory": "Cryptocurrency mining",
            "operatingSystem": "Windows 10, Windows 11 (64-bit)",
            "softwareVersion": VERSION,
            "downloadUrl": f"{SITE}/download/MINTRO-Setup-{VERSION}.exe",
            "image": IMAGE,
            "license": "https://www.gnu.org/licenses/gpl-3.0.html",
            "isAccessibleForFree": True,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "author": {"@id": ORG["@id"]},
            "publisher": {"@id": ORG["@id"]},
            "sameAs": ["https://github.com/aiteleresearch/mintro"],
        })
        faqs = re.findall(r"<details>\s*<summary>(.*?)</summary>\s*<div class=\"ans\">(.*?)</div>\s*</details>", body, re.S)
        if faqs:
            graph.append({
                "@type": "FAQPage",
                "@id": f"{SITE}/#faq",
                "url": f"{SITE}/#faq",
                "isPartOf": {"@id": f"{SITE}/#webpage"},
                "mainEntity": [
                    {"@type": "Question", "name": text(q), "acceptedAnswer": {"@type": "Answer", "text": text(a)}}
                    for q, a in faqs
                ],
            })
    else:
        webpage["breadcrumb"] = {"@id": f"{url}#breadcrumb"}
        graph.append(webpage)
        graph.append({
            "@type": "BreadcrumbList",
            "@id": f"{url}#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "MINTRO", "item": f"{SITE}/"},
                {"@type": "ListItem", "position": 2, "name": crumb, "item": url},
            ],
        })
        if kind == "ContactPage":
            webpage["mainEntity"] = {"@id": ORG["@id"]}
    return {"@context": "https://schema.org", "@graph": graph}


def refresh(page: str, file: pathlib.Path) -> bool:
    src = file.read_text("utf-8")
    end = src.index("</head>")
    head, rest = src[: end + len("</head>")], src[end + len("</head>"):]
    path, crumb, kind, _, _ = PAGES[page]
    url = f"{SITE}{path}"

    head = head.replace(OLD_HOST + "/", SITE + "/").replace(OLD_HOST, SITE)
    head = re.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', head)
    head = set_meta(head, "name", "robots", "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1", after="theme-color")
    head = set_meta(head, "name", "author", "Aitele Research LLP", after="robots")
    head = set_meta(head, "name", "application-name", "MINTRO", after="author")
    head = set_meta(head, "name", "apple-mobile-web-app-title", "MINTRO", after="application-name")
    head = set_meta(head, "property", "og:url", url, after="og:site_name")
    head = set_meta(head, "property", "og:locale", "en_US", after="og:site_name")
    head = set_meta(head, "property", "og:image", IMAGE, after="og:description")
    head = set_meta(head, "property", "og:image:type", "image/png", after="og:image")
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

    ld = json.dumps(jsonld(page, path, crumb, kind, head, rest), ensure_ascii=False, indent=1)
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
    return dt.date.fromtimestamp((ROOT / "docs" / page).stat().st_mtime).isoformat()


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
    (out / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /download/\nDisallow: /v1/\n\n"
        f"Sitemap: {SITE}/sitemap.xml\n", "utf-8", newline="\n")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = pathlib.Path(args[0]) if args else ROOT / "docs"
    changed = [p for p in PAGES if (target / p).exists() and refresh(p, target / p)]
    print(f"seo: {len(changed)} page(s) updated in {target} (MINTRO {VERSION})")
    if "--sitemap" in sys.argv:
        write_sitemap(target)
        print(f"seo: sitemap.xml + robots.txt written for {SITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
