"""Built-in authentication: password (scrypt) + optional TOTP + passkeys (WebAuthn).

Sessions are random tokens in an HttpOnly cookie; only their SHA-256 is stored.
Lost access: `docker exec ft-actu python auth.py reset` then follow the setup link in the logs.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import segno
import webauthn
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

DATA = Path(os.environ.get("DATA_DIR", "/data"))
AUTH_FILE = DATA / "auth.json"
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8080").rstrip("/")
RP_ID = urlparse(BASE_URL).hostname
SESSION_IDLE = 7 * 86400      # sliding expiry
SESSION_MAX = 30 * 86400      # absolute expiry
MIN_PASSWORD = 12
MAX_FAILS, LOCK_S = 5, 15 * 60

lock = threading.Lock()
fails = {}       # ip -> [count, first_failure_ts]
pending = {}     # short-lived state: pre-2FA logins and WebAuthn challenges, key -> (expires, data)


def load():
    return json.loads(AUTH_FILE.read_text()) if AUTH_FILE.exists() else {"sessions": {}, "passkeys": []}


def save(db):
    tmp = AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(AUTH_FILE)


def configured():
    return "password" in load()


# --- password ---------------------------------------------------------------

def hash_password(pw):
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 2 ** 20)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_password(pw, stored):
    _, salt, h = stored.split("$")
    got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=2 ** 15, r=8, p=1, maxmem=64 * 2 ** 20)
    return hmac.compare_digest(got, base64.b64decode(h))


def password_problem(pw, confirm):
    if pw != confirm:
        return "Les deux mots de passe sont différents."
    if len(pw) < MIN_PASSWORD:
        return f"{MIN_PASSWORD} caractères minimum."
    return None


def set_password(pw):
    with lock:
        db = load()
        db["password"] = hash_password(pw)
        db["sessions"] = {}  # changing the password logs every device out
        save(db)


# --- rate limiting ----------------------------------------------------------

def blocked(ip):
    """Per-IP lock, plus a global one in case the client IP is spoofable (no proxy in front)."""
    for key, limit in ((ip, MAX_FAILS), ("*", 4 * MAX_FAILS)):
        count, first = fails.get(key, (0, 0))
        if time.time() - first > LOCK_S:
            fails.pop(key, None)
        elif count >= limit:
            return True
    return False


def failed(ip):
    for key in (ip, "*"):
        count, first = fails.get(key, (0, time.time()))
        fails[key] = [count + 1, first]


# --- TOTP (RFC 6238, SHA-1, 6 digits, 30 s) ---------------------------------

def totp(secret, counter):
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** 6:06d}"


def totp_ok(db, code, secret=None):
    """Accepts the previous/current/next code; a code is never accepted twice."""
    secret = secret or db.get("totp")
    code = "".join(c for c in code if c.isdigit())
    now = int(time.time()) // 30
    for counter in (now - 1, now, now + 1):
        if counter > db.get("totp_last", 0) and hmac.compare_digest(totp(secret, counter), code):
            db["totp_last"] = counter
            return True
    return False


def new_totp_secret():
    return base64.b32encode(os.urandom(20)).decode()


def totp_qr_svg(secret):
    uri = (f"otpauth://totp/{quote('Actualisation FT')}:{quote(RP_ID)}?secret={secret}"
           f"&issuer={quote('Actualisation FT')}")
    return segno.make(uri, error="m").svg_inline(scale=5, dark="#1b2233", light="#ffffff")


# --- sessions ---------------------------------------------------------------

def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(ua):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with lock:
        db = load()
        db["sessions"][_h(token)] = {"created": now, "seen": now, "ua": (ua or "")[:120]}
        save(db)
    return token


def session_ok(token):
    if not token:
        return False
    with lock:
        db = load()
        s = db["sessions"].get(_h(token))
        now = time.time()
        if not s or now - s["seen"] > SESSION_IDLE or now - s["created"] > SESSION_MAX:
            if s:
                del db["sessions"][_h(token)]
                save(db)
            return False
        if now - s["seen"] > 300:  # avoid a disk write per request
            s["seen"] = now
            save(db)
        return True


def end_session(token, others=False):
    with lock:
        db = load()
        keep = _h(token or "")  # others=False: end this session; others=True: end all but this one
        db["sessions"] = {k: v for k, v in db["sessions"].items() if (k == keep) == others}
        save(db)


def remember(data, ttl=300):
    key = secrets.token_urlsafe(24)
    now = time.time()
    for k in [k for k, (exp, _) in pending.items() if exp < now]:
        del pending[k]
    pending[key] = (now + ttl, data)
    return key


def recall(key):
    exp, data = pending.pop(key or "", (0, None))
    return data if exp > time.time() else None


# --- passkeys ---------------------------------------------------------------

def passkey_register_begin():
    db = load()
    opts = webauthn.generate_registration_options(
        rp_id=RP_ID, rp_name="Actualisation France Travail", user_name="admin",
        user_id=b"ft-actu-admin",
        exclude_credentials=[PublicKeyCredentialDescriptor(id=webauthn.base64url_to_bytes(p["id"]))
                             for p in db["passkeys"]],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED))
    return remember(opts.challenge), json.loads(webauthn.options_to_json(opts))


def passkey_register_finish(state, credential, name):
    challenge = recall(state)
    if not challenge:
        raise ValueError("demande expirée")
    v = webauthn.verify_registration_response(
        credential=credential, expected_challenge=challenge, expected_rp_id=RP_ID,
        expected_origin=BASE_URL, require_user_verification=True)
    with lock:
        db = load()
        db["passkeys"].append({"id": bytes_to_base64url(v.credential_id),
                               "key": bytes_to_base64url(v.credential_public_key),
                               "count": v.sign_count, "name": (name or "Passkey")[:40],
                               "created": time.strftime("%d/%m/%Y")})
        save(db)


def passkey_login_begin():
    db = load()
    opts = webauthn.generate_authentication_options(
        rp_id=RP_ID, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=webauthn.base64url_to_bytes(p["id"]))
                           for p in db["passkeys"]])
    return remember(opts.challenge), json.loads(webauthn.options_to_json(opts))


def passkey_login_finish(state, credential):
    challenge = recall(state)
    if not challenge:
        raise ValueError("demande expirée")
    with lock:
        db = load()
        pk = next((p for p in db["passkeys"] if p["id"] == credential.get("id")), None)
        if not pk:
            raise ValueError("passkey inconnue")
        v = webauthn.verify_authentication_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=RP_ID,
            expected_origin=BASE_URL, credential_public_key=webauthn.base64url_to_bytes(pk["key"]),
            credential_current_sign_count=pk["count"], require_user_verification=True)
        pk["count"] = v.new_sign_count
        save(db)


def delete_passkey(pid):
    with lock:
        db = load()
        db["passkeys"] = [p for p in db["passkeys"] if p["id"] != pid]
        save(db)


# --- first run / recovery ---------------------------------------------------

setup_token = None


def announce_setup():
    """No account yet: print a one-time setup link (only whoever reads the logs can claim the app)."""
    global setup_token
    if not configured():
        setup_token = secrets.token_urlsafe(24)
        print(f"\n*** Première configuration : ouvre {BASE_URL}/setup?token={setup_token}\n", flush=True)


if __name__ == "__main__" and sys.argv[1:] == ["reset"]:
    if AUTH_FILE.exists():
        AUTH_FILE.unlink()
    print("Accès réinitialisé (mot de passe, 2FA, passkeys, sessions). Redémarre le container "
          "et ouvre le lien de configuration affiché dans les logs.")
