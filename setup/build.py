"""Build the Windows package: dist\\MINTRO-Setup-<version>.exe

    py -3.12 setup\\build.py

1. MINTRO.exe and its files (PyInstaller, one folder, no console window)
2. MINTRO-Setup-<version>.exe: one file holding that folder, which installs it for the current user
3. MINTRO-Update-<version>.zip + .sig: the same folder, for installed copies to update themselves, signed with
   the publisher key (%USERPROFILE%\\MINTRO-publisher) when it's on this PC. Upload all three to the release.
Needs Python 3.12 with pywebview and PyInstaller installed.

Code signing (optional, recommended for anything you hand out): set one of these and both MINTRO.exe and the
setup file get signed with signtool and timestamped. Unsigned builds still work; Windows SmartScreen just
warns more, and antivirus scanners trust them less.
    MINTRO_SIGN_THUMBPRINT  SHA-1 thumbprint of a certificate in your Windows certificate store; this is how
                            USB-token and cloud-HSM certificates (EV and OV) show up
    MINTRO_SIGN_PFX         a .pfx file, with MINTRO_SIGN_PASSWORD
    MINTRO_SIGN_TIMESTAMP   timestamp server (default http://timestamp.digicert.com)
    MINTRO_SIGNTOOL         signtool.exe, if it isn't in the Windows SDK folder or on PATH
"""
import os
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


def sign(exe: Path) -> None:
    """Sign and timestamp exe if a certificate is configured (see the module docstring)."""
    thumb, pfx = os.environ.get("MINTRO_SIGN_THUMBPRINT"), os.environ.get("MINTRO_SIGN_PFX")
    if not (thumb or pfx):
        print(f"not signed (no certificate configured): {exe.name}")
        return
    tool = signtool()
    if not tool:
        sys.exit("signtool.exe not found: install the Windows SDK or set MINTRO_SIGNTOOL")
    who = ["/sha1", thumb] if thumb else ["/f", pfx, "/p", os.environ.get("MINTRO_SIGN_PASSWORD", "")]
    stamp = os.environ.get("MINTRO_SIGN_TIMESTAMP", "http://timestamp.digicert.com")
    subprocess.run([tool, "sign", "/fd", "sha256", "/tr", stamp, "/td", "sha256", "/d", "MINTRO", *who, str(exe)], check=True)
    subprocess.run([tool, "verify", "/pa", str(exe)], check=True)
    print(f"signed: {exe.name}")


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir()
    DIST.mkdir(exist_ok=True)
    icon = BUILD / "mintro.ico"
    write_ico(str(icon))
    print("icon:", icon)

    # 1) the app
    pyinstaller("--windowed", "--name", "MINTRO", "--icon", str(icon), "--distpath", str(BUILD / "app"),
                "--add-data", f"{ROOT / 'mintro' / 'web'};mintro/web",
                "--collect-all", "webview", "--collect-all", "clr_loader", "--collect-all", "pythonnet",
                str(HERE / "launcher.py"))
    app = BUILD / "app" / "MINTRO"
    sign(app / "MINTRO.exe")
    payload = BUILD / "MINTRO.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app))
    print(f"app: {app} ({payload.stat().st_size / 1e6:.0f} MB zipped)")

    # 2) the installer
    name = f"MINTRO-Setup-{__version__}"
    pyinstaller("--onefile", "--windowed", "--name", name, "--icon", str(icon), "--distpath", str(DIST),
                "--add-data", f"{payload};.", "--add-data", f"{icon};.",
                str(HERE / "setup_main.py"))
    setup = DIST / f"{name}.exe"
    sign(setup)

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


if __name__ == "__main__":
    main()
