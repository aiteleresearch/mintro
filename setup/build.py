"""Build the Windows package: dist\\MINTRO-Setup-<version>.exe

    py -3.12 setup\\build.py

1. MINTRO.exe and its files (PyInstaller, one folder, no console window)
2. MINTRO-Setup-<version>.exe: one file holding that folder, which installs it for the current user
3. MINTRO-Update-<version>.zip + .sig: the same folder, for installed copies to update themselves, signed with
   the publisher key (%USERPROFILE%\\MINTRO-publisher) when it's on this PC. Upload all three to the release.
Needs Python 3.12 with pywebview and PyInstaller installed.

Both exes carry version information (publisher, product, version, copyright), which Windows shows in
Properties > Details and antivirus scanners weigh.

Code signing (recommended for anything you hand out; docs/SIGNING.md explains how to get a certificate): set
one of these and both MINTRO.exe and the setup file get signed with signtool and timestamped. Unsigned builds
still work; Windows SmartScreen just warns more, and antivirus scanners trust them less.
    MINTRO_SIGN_THUMBPRINT  SHA-1 thumbprint of a certificate in your Windows certificate store; this is how
                            USB-token, SimplySign (Certum) and other cloud-HSM certificates show up
    MINTRO_SIGN_PFX         a .pfx file, with MINTRO_SIGN_PASSWORD
    MINTRO_SIGN_DLIB        Azure Artifact Signing (Trusted Signing): the path to Azure.CodeSigning.Dlib.dll,
                            with MINTRO_SIGN_METADATA, the metadata.json naming your account and profile
    MINTRO_SIGN_TIMESTAMP   timestamp server (default http://timestamp.digicert.com, or Microsoft's for Azure)
    MINTRO_SIGNTOOL         signtool.exe, if it isn't in the Windows SDK folder or on PATH
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD, DIST = ROOT / "build", ROOT / "dist"
sys.path[:0] = [str(ROOT), str(HERE)]
from make_icon import write_ico  # noqa: E402
from mintro import __version__  # noqa: E402


def pyinstaller(*args: str) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
           "--workpath", str(BUILD / "work"), "--specpath", str(BUILD), "--paths", str(ROOT), *args]
    print(">", " ".join(cmd[3:]), flush=True)
    subprocess.run(cmd, check=True, cwd=BUILD)  # not the project root: keep its folders off PyInstaller's path


def signtool() -> str | None:
    if os.environ.get("MINTRO_SIGNTOOL"):
        return os.environ["MINTRO_SIGNTOOL"]
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    found = sorted(kits.glob("10.*/x64/signtool.exe"))
    return str(found[-1]) if found else shutil.which("signtool")


WEBSITE = "https://mintro.aiteleresearch.com"
SIGNED: dict[str, bool] = {}


def signer() -> tuple[list[str], str] | None:
    """signtool arguments for the configured certificate, and the default timestamp server; None if none is set."""
    env = os.environ.get
    if env("MINTRO_SIGN_DLIB"):
        if not env("MINTRO_SIGN_METADATA"):
            sys.exit("MINTRO_SIGN_DLIB is set: also set MINTRO_SIGN_METADATA (the metadata.json for Azure Artifact Signing)")
        return ["/dlib", env("MINTRO_SIGN_DLIB"), "/dmdf", env("MINTRO_SIGN_METADATA")], "http://timestamp.acs.microsoft.com"
    if env("MINTRO_SIGN_THUMBPRINT"):
        return ["/sha1", env("MINTRO_SIGN_THUMBPRINT").replace(" ", "")], "http://timestamp.digicert.com"
    if env("MINTRO_SIGN_PFX"):
        return ["/f", env("MINTRO_SIGN_PFX"), "/p", env("MINTRO_SIGN_PASSWORD", "")], "http://timestamp.digicert.com"
    return None


def sign(exe: Path, description: str) -> None:
    """Sign and timestamp exe if a certificate is configured (see the module docstring)."""
    how = signer()
    SIGNED[exe.name] = False
    if not how:
        print(f"not signed (no certificate configured): {exe.name}")
        return
    tool = signtool()
    if not tool:
        sys.exit("signtool.exe not found: install the Windows SDK or set MINTRO_SIGNTOOL")
    who, default_stamp = how
    stamp = os.environ.get("MINTRO_SIGN_TIMESTAMP", default_stamp)
    subprocess.run([tool, "sign", "/fd", "SHA256", "/tr", stamp, "/td", "SHA256", "/d", description, "/du", WEBSITE,
                    *who, str(exe)], check=True)
    subprocess.run([tool, "verify", "/pa", str(exe)], check=True)
    SIGNED[exe.name] = True
    print(f"signed: {exe.name}")


RELEASES = ROOT / "releases"


def keep_in_repo(setup: Path) -> Path:
    """Put the new installer in releases/ (tracked by git) in place of the previous one, with its SHA-256.

    The repository always holds exactly one installer, the latest; older ones stay in git history.
    """
    import hashlib
    RELEASES.mkdir(exist_ok=True)
    for old in RELEASES.glob("MINTRO-Setup-*.exe"):
        if old.name != setup.name:
            old.unlink()
    copy = RELEASES / setup.name
    shutil.copy2(setup, copy)
    digest = hashlib.sha256(copy.read_bytes()).hexdigest()
    (RELEASES / "SHA256SUMS.txt").write_text(f"{digest}  {setup.name}\n", "utf-8", newline="\n")
    return copy


def version_file(name: str, description: str, original: str) -> Path:
    """Windows version information for an exe: what Properties > Details shows."""
    nums = tuple((list(map(int, re.findall(r"\d+", __version__)[:4])) + [0, 0, 0, 0])[:4])
    path = BUILD / f"{name}.version.txt"
    strings = {"CompanyName": "aitele research", "FileDescription": description, "FileVersion": __version__,
               "InternalName": name, "LegalCopyright": f"\u00a9 {datetime.date.today().year} aitele research. GPL-3.0.",
               "OriginalFilename": original, "ProductName": "MINTRO", "ProductVersion": __version__}
    table = ",\n        ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        {table}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir()
    DIST.mkdir(exist_ok=True)
    icon = BUILD / "mintro.ico"
    write_ico(str(icon))
    print("icon:", icon)

    # 1) the app
    webview = ["--collect-all", "webview", "--collect-all", "clr_loader", "--collect-all", "pythonnet"]
    pyinstaller("--windowed", "--name", "MINTRO", "--icon", str(icon), "--distpath", str(BUILD / "app"),
                "--version-file", str(version_file("MINTRO", "MINTRO", "MINTRO.exe")),
                "--add-data", f"{ROOT / 'mintro' / 'web'};mintro/web", *webview,
                str(HERE / "launcher.py"))
    app = BUILD / "app" / "MINTRO"
    sign(app / "MINTRO.exe", "MINTRO")
    payload = BUILD / "MINTRO.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app))
    print(f"app: {app} ({payload.stat().st_size / 1e6:.0f} MB zipped)")

    # 2) the installer
    name = f"MINTRO-Setup-{__version__}"
    # pywebview's other platforms pull these in on paper; the setup window never imports them (28 MB less to download)
    slim = [arg for mod in ("numpy", "PIL", "cryptography", "bcrypt") for arg in ("--exclude-module", mod)]
    pyinstaller("--onefile", "--windowed", "--name", name, "--icon", str(icon), "--distpath", str(DIST),
                "--version-file", str(version_file(name, "MINTRO Setup", f"{name}.exe")),
                "--add-data", f"{payload};.", "--add-data", f"{icon};.", "--add-data", f"{HERE / 'installer.html'};.",
                *webview, *slim, str(HERE / "setup_main.py"))
    setup = DIST / f"{name}.exe"
    sign(setup, "MINTRO Setup")
    in_repo = keep_in_repo(setup)

    # 3) the self-update package
    update = DIST / f"MINTRO-Update-{__version__}.zip"
    shutil.copy(payload, update)
    sys.path.insert(0, str(ROOT / "publisher"))
    import mintro_keys
    if mintro_keys.KEY_FILE.exists():
        print("update signature:", mintro_keys.sign_update(update, __version__))
    else:
        print(f"update NOT signed (no publisher key at {mintro_keys.KEY_FILE}); installed copies won't take it")
    print(f"\nDone: {setup} ({setup.stat().st_size / 1e6:.0f} MB)\n      {update} ({update.stat().st_size / 1e6:.0f} MB)")
    print(f"      {in_repo} (the copy kept in the repository: commit it with the release)")
    for exe, ok in SIGNED.items():
        print(f"  {'SIGNED  ' if ok else 'UNSIGNED'} {exe}")
    if not all(SIGNED.values()):
        print("  Unsigned exes work, but SmartScreen warns about them. docs/SIGNING.md: how to sign the release.")


if __name__ == "__main__":
    main()
