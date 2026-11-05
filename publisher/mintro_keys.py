"""The publisher's signing key: signs update packages and the coin listings feed (publisher only; not in the app).

    py publisher\\mintro_keys.py init                                                   # once: make the key
    py publisher\\mintro_keys.py sign-update dist\\MINTRO-Update-0.4.0.zip --version 0.4.0   # build.py does this
    py publisher\\mintro_keys.py sign-listings listings\\listings.json                     # admin.py does this

Installed copies only install an update, or use a listing, whose signature checks out against the public key
in mintro/signing.py. The private key is stored OUTSIDE the repository
(%USERPROFILE%\\MINTRO-publisher\\license-signing-key.json). Back it up somewhere safe and never share or
commit it: anyone with it could push code or coins to every MINTRO user.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mintro import signing  # noqa: E402

KEY_FILE = Path(os.environ.get("USERPROFILE", Path.home())) / "MINTRO-publisher" / "license-signing-key.json"


def init() -> None:
    if KEY_FILE.exists():
        sys.exit(f"A signing key already exists at {KEY_FILE}. Replacing it means every installed copy rejects "
                 "your future updates and listings until they install a release made with the new key.")
    secret = secrets.token_bytes(32)
    public = signing.public_key(secret).hex()
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(json.dumps({"secret": secret.hex(), "public": public}), encoding="utf-8")
    source = ROOT / "mintro" / "signing.py"
    text = re.sub(r'PUBLIC_KEY_HEX = "[^"]*"', f'PUBLIC_KEY_HEX = "{public}"', source.read_text(encoding="utf-8"))
    source.write_text(text, encoding="utf-8")
    print(f"Signing key saved to {KEY_FILE} (back it up; never share it).\nPublic key written to {source}: {public}")


def _key() -> tuple[bytes, str]:
    saved = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    signing.PUBLIC_KEY_HEX = saved["public"]  # so the self-checks below test what the app will test
    return bytes.fromhex(saved["secret"]), saved["public"]


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign_update(path: Path, version: str) -> Path:
    """Write <package>.sig: the publisher's signature over the version and the package's SHA-256."""
    from mintro import updater
    secret, _ = _key()
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    sig = {"version": version, "sha256": digest, "signature": _b64(signing.sign(secret, updater.signed_message(version, digest)))}
    if not updater.verify_signature(sig, version, digest):
        sys.exit("Signature check failed: is mintro/signing.py's public key this signing key's?")
    out = Path(f"{path}.sig")
    out.write_text(json.dumps(sig), encoding="utf-8")
    return out


def sign_listings(path: Path) -> Path:
    """Write <feed>.sig for the listings feed (its serial number is part of what's signed)."""
    from mintro import listings
    secret, _ = _key()
    raw = Path(path).read_bytes()
    serial = int(json.loads(raw)["serial"])
    digest = hashlib.sha256(raw).hexdigest()
    sig = {"serial": serial, "sha256": digest, "signature": _b64(signing.sign(secret, listings.signed_message(serial, digest)))}
    if not listings.verify(raw, sig):
        sys.exit("Signature check failed: is mintro/signing.py's public key this signing key's?")
    out = Path(f"{path}.sig")
    out.write_text(json.dumps(sig), encoding="utf-8")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    u = sub.add_parser("sign-update")
    u.add_argument("package")
    u.add_argument("--version", required=True)
    s = sub.add_parser("sign-listings")
    s.add_argument("feed")
    a = p.parse_args()
    if a.cmd == "init":
        init()
    elif a.cmd == "sign-update":
        print(sign_update(Path(a.package), a.version))
    else:
        print(sign_listings(Path(a.feed)))
