# Search, AI search and indexing

How MINTRO's website gets found: by Google and Bing, by AI assistants (ChatGPT search, Perplexity, Claude,
Gemini, Copilot), and quickly after every change. Most of it is automated by `setup/seo.py`; a few one-time steps
need your accounts.

## What each page is for

| Page | What people search for | Structured data |
|---|---|---|
| `/` | free crypto mining app, crypto miner for Windows, mine crypto on a laptop/PC | SoftwareApplication, FAQPage |
| `/download.html` | download MINTRO, crypto miner download Windows, "Windows protected your PC" with a miner | SoftwareApplication, HowTo |
| `/coins.html` | coins you can mine with a CPU, RandomX / GhostRider / yespower mining, mine Monero / Zephyr / Salvium / Raptoreum | ItemList |
| `/mine-crypto-on-a-laptop.html` | how to mine crypto on a laptop, is laptop mining worth it, will mining damage my laptop | Article |
| `/faq.html` | 27 long-tail questions: earnings, electricity, Bitcoin, GPU, battery, antivirus, wallets, tax | FAQPage |
| `/risk.html`, `/contact.html`, legal pages | trust pages | WebPage, ContactPage |

Every page links to the others from its footer, and the home page links to each one from the section it belongs to.

## What `setup/seo.py` keeps right

- **Head tags** on every page: canonical and hreflang on `https://mintro.aiteleresearch.com`, robots with full
  snippets and large image previews, share-card tags, author.
- **JSON-LD** per page (table above), with breadcrumbs. Questions, install steps and coins are read from the pages
  themselves, so the structured data can't drift from what people see.
- **Facts**: the version and installer size wherever a page marks them with `data-seo`.
- **`coins.html`**: `--coins` rebuilds its table from the same live catalog the app mines, with the date.
- **`llms.txt` and `llms-full.txt`** ([llmstxt.org](https://llmstxt.org)): a summary of MINTRO and the full text of
  every page as Markdown, for AI assistants and answer engines.
- **`sitemap.xml`** (each page's last change from git) and **`robots.txt`**, which welcomes every search engine
  and AI crawler by name and keeps `/api`, `/download` and `/v1` out. Written for the deploy copy (`--sitemap`).
- **IndexNow**: the key file `docs/4d6322414e141882b445ae4b9da4763a.txt`, and `--indexnow` to submit every page.
  Bing, Yandex, Seznam, Naver and Yep share submissions; ChatGPT search uses Bing's index, so this is the fastest
  route into AI answers too.

## On every release or page change

1. `py -3.12 setup\seo.py --coins` (refreshes the coin list, then everything else). Commit and push.
2. Deploy the website as usual (`docs/UPDATES.md`); the deploy runs `seo.py <dir> --sitemap`.
3. Once it's live: `py -3.12 setup\seo.py --indexnow`. It prints whether IndexNow accepted the pages.

## One-time setup (needs your accounts)

1. **Google Search Console** (search.google.com/search-console): add a *Domain* property for
   `mintro.aiteleresearch.com` (or `aiteleresearch.com`), verify it with the DNS TXT record it gives you, then
   *Sitemaps* > submit `https://mintro.aiteleresearch.com/sitemap.xml`. Use *URL inspection* > *Request indexing*
   on the five main pages for the first crawl. Google no longer accepts sitemap pings, so this is the way in.
2. **Bing Webmaster Tools** (bing.com/webmasters): *Import from Google Search Console* (one click once step 1 is
   done), or verify the same way. Submit the sitemap there too. IndexNow submissions then show under *IndexNow*.
3. Check the structured data with Google's Rich Results Test and the Schema Markup Validator (validator.schema.org).

## What moves rankings beyond the site

On-page work makes the site easy to understand and quick to index; how high it ranks for broad terms also depends
on other sites pointing to it. The highest-value places for a free, open-source Windows miner:

- the GitHub repository: a description, the website as its homepage, and topics such as `crypto-mining`,
  `cpu-mining`, `monero`, `randomx`, `xmrig`, `windows`;
- software directories: AlternativeTo (as an alternative to other miners), Softpedia, MajorGeeks, and a
  `winget` package so `winget install MINTRO` works;
- communities where people ask about laptop mining (Reddit's mining and coin communities, coin projects' Discords)
  and the coins MINTRO lists, which can link to their coin page;
- Product Hunt and Hacker News (*Show HN*) for a launch.

Keep the content honest (small earnings, a lottery not an income): search engines and AI assistants both favour
pages that answer the question straight, and it's what the pages already do.
