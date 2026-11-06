"""Build the website deployment package: dist\\mintro-website-<version>.zip

    py -3.12 setup\\build_site.py

The zip holds the site (docs/ minus the guides) and deploy/website/install.sh, which installs it on a
Debian/Ubuntu server with nginx and HTTPS for any domain. See deploy/website/README.txt.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mintro import __version__  # noqa: E402

DOCS, DEPLOY, DIST = ROOT / "docs", ROOT / "deploy" / "website", ROOT / "dist"
GITHUB_PAGES = "https://aiteleresearch.github.io/mintro"  # the site's address in the repo copy
PLACEHOLDER = "https://__MINTRO_DOMAIN__"                  # install.sh puts the real domain here
TOP = "mintro-website"


def site_files() -> list[Path]:
    files = [DOCS / "index.html", DOCS / "404.html", DOCS / "site.webmanifest"]
    files += sorted(p for p in (DOCS / "assets").rglob("*") if p.is_file())
    return files


def main() -> None:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"mintro-website-{__version__}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in site_files():
            data = f.read_bytes()
            if f.name == "index.html":
                data = data.replace(GITHUB_PAGES.encode(), PLACEHOLDER.encode())
                assert PLACEHOLDER.encode() in data, "index.html has no site address to replace"
            z.writestr(f"{TOP}/site/{f.relative_to(DOCS).as_posix()}", data)
        for name, mode in (("install.sh", 0o755), ("README.txt", 0o644)):
            text = (DEPLOY / name).read_bytes().replace(b"\r\n", b"\n")  # Linux line endings, whatever git did
            info = zipfile.ZipInfo(f"{TOP}/{name}")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100000 | mode) << 16  # a regular file with Unix permissions
            info.create_system = 3                        # made on "Unix", so unzip applies those permissions
            z.writestr(info, text)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB, {len(site_files())} site files)")


if __name__ == "__main__":
    main()
