"""
Secure Shift - authentication and persistence.

Two interchangeable backends expose the same interface:

* FirebaseStore - Firebase Authentication (email/password, REST) + Cloud Firestore.
* LocalStore    - SQLite + PBKDF2 password hashes. Used automatically until the
                  Firebase settings in config.py are filled in.

Data model (identical in both backends)
    users/{uid}                      profile: email, created_at, last_login_at, active_artifact_id
    users/{uid}/artifacts/{id}       submitted files (name, content, size, sha256, source)
    users/{uid}/audits/{id}          audit runs (artifact_id, controls, model, result, latency)
    users/{uid}/messages/{id}        cross-examination chat (artifact_id, role, content, model)
    users/{uid}/events/{id}          sign-in / sign-out / failover / error trail
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

log = logging.getLogger("secure_shift.storage")

COLLECTIONS = ("artifacts", "audits", "messages", "events")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD = 8


def utcnow_iso() -> str:
    """Sortable UTC timestamp used as `created_at` everywhere."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def mask_email(email: str) -> str:
    """For logs: jane.doe@acme.com -> j***@acme.com"""
    if "@" not in (email or ""):
        return "***"
    name, domain = email.split("@", 1)
    return f"{name[:1]}***@{domain}"


class AuthError(Exception):
    """User-facing authentication problem (message is safe to display)."""


class StorageError(Exception):
    """Persistence problem."""


@dataclass(frozen=True)
class User:
    uid: str
    email: str


def _pbkdf2_sha256(password: bytes, salt: bytes, rounds: int) -> bytes:
    """PBKDF2-HMAC-SHA256 (32-byte key). Uses OpenSSL when available, pure Python otherwise."""
    if hasattr(hashlib, "pbkdf2_hmac"):
        return hashlib.pbkdf2_hmac("sha256", password, salt, rounds)
    prf = hmac.new(password, digestmod=hashlib.sha256)  # interpreters built without OpenSSL
    h = prf.copy()
    h.update(salt + b"\x00\x00\x00\x01")
    u = h.digest()
    acc = int.from_bytes(u, "big")
    for _ in range(rounds - 1):
        h = prf.copy()
        h.update(u)
        u = h.digest()
        acc ^= int.from_bytes(u, "big")
    return acc.to_bytes(32, "big")


def _validate(email: str, password: str, signup: bool = False) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if not password:
        raise AuthError("Enter your password.")
    if signup and len(password) < MIN_PASSWORD:
        raise AuthError(f"Use at least {MIN_PASSWORD} characters for your password.")
    if len(password) > 128:
        raise AuthError("Password is too long (128 characters max).")
    return email


# ======================================================================
# Local demo backend (SQLite)
# ======================================================================
class LocalStore:
    kind = "local"
    label = "Local demo store"
    supports_password_reset = False
    _PBKDF2_ROUNDS = 310_000

    def __init__(self, path: str, degraded_reason: str | None = None):
        self.path = path
        self.degraded_reason = degraded_reason
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute(
                """CREATE TABLE IF NOT EXISTS users (
                       uid TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                       pw_hash TEXT NOT NULL, salt TEXT NOT NULL,
                       created_at TEXT NOT NULL, profile TEXT NOT NULL DEFAULT '{}')"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS records (
                       id TEXT PRIMARY KEY, uid TEXT NOT NULL, collection TEXT NOT NULL,
                       created_at TEXT NOT NULL, data TEXT NOT NULL)"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_records ON records(uid, collection, created_at)")
        log.info("Local store ready at %s", path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _hash(self, password: str, salt_hex: str) -> str:
        return _pbkdf2_sha256(password.encode(), bytes.fromhex(salt_hex), self._PBKDF2_ROUNDS).hex()

    # --- auth -------------------------------------------------------
    def sign_up(self, email: str, password: str) -> User:
        email = _validate(email, password, signup=True)
        salt = secrets.token_hex(16)
        uid = "local_" + uuid.uuid4().hex[:24]
        now = utcnow_iso()
        profile = json.dumps({"email": email, "created_at": now})
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO users(uid,email,pw_hash,salt,created_at,profile) VALUES(?,?,?,?,?,?)",
                    (uid, email, self._hash(password, salt), salt, now, profile),
                )
        except sqlite3.IntegrityError:
            raise AuthError("An account with this email already exists. Sign in instead.") from None
        return User(uid, email)

    def sign_in(self, email: str, password: str) -> User:
        email = _validate(email, password)
        with self._conn() as c:
            row = c.execute("SELECT uid,email,pw_hash,salt FROM users WHERE email=?", (email,)).fetchone()
        if row is None:
            self._hash(password, "00" * 16)  # equalise timing so emails can't be enumerated
            raise AuthError("Incorrect email or password.")
        if not hmac.compare_digest(self._hash(password, row["salt"]), row["pw_hash"]):
            raise AuthError("Incorrect email or password.")
        return User(row["uid"], row["email"])

    def send_password_reset(self, email: str) -> None:
        raise AuthError("Password reset becomes available once Firebase is connected.")

    # --- data -------------------------------------------------------
    def add(self, uid: str, collection: str, data: dict) -> str:
        rid = uuid.uuid4().hex
        payload = {**data, "created_at": data.get("created_at") or utcnow_iso()}
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO records(id,uid,collection,created_at,data) VALUES(?,?,?,?,?)",
                    (rid, uid, collection, payload["created_at"], json.dumps(payload, default=str)),
                )
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc
        return rid

    def list(self, uid: str, collection: str, limit: int = 500) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id,data FROM records WHERE uid=? AND collection=? ORDER BY created_at DESC LIMIT ?",
                (uid, collection, limit),
            ).fetchall()
        out = [{**json.loads(r["data"]), "id": r["id"]} for r in rows]
        out.reverse()  # oldest first
        return out

    def get_profile(self, uid: str) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT profile FROM users WHERE uid=?", (uid,)).fetchone()
        return json.loads(row["profile"]) if row else {}

    def update_profile(self, uid: str, data: dict) -> None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT profile FROM users WHERE uid=?", (uid,)).fetchone()
            merged = {**(json.loads(row["profile"]) if row else {}), **data}
            c.execute("UPDATE users SET profile=? WHERE uid=?", (json.dumps(merged, default=str), uid))


# ======================================================================
# Firebase backend (Auth REST + Firestore via Admin SDK)
# ======================================================================
_FIREBASE_ERRORS = {
    "EMAIL_EXISTS": "An account with this email already exists. Sign in instead.",
    "EMAIL_NOT_FOUND": "Incorrect email or password.",
    "INVALID_PASSWORD": "Incorrect email or password.",
    "INVALID_LOGIN_CREDENTIALS": "Incorrect email or password.",
    "USER_DISABLED": "This account has been disabled. Contact your administrator.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Wait a few minutes and try again.",
    "WEAK_PASSWORD": f"Password is too weak. Use at least {MIN_PASSWORD} characters.",
    "INVALID_EMAIL": "Enter a valid email address.",
    "MISSING_PASSWORD": "Enter your password.",
    "OPERATION_NOT_ALLOWED": "Email/password sign-in is disabled. Enable it in Firebase console > Authentication > Sign-in method.",
    "CONFIGURATION_NOT_FOUND": "Firebase Authentication is not set up. Open Firebase console > Authentication > Get started.",
    "PASSWORD_LOGIN_DISABLED": "Email/password sign-in is disabled for this project.",
}


class FirebaseStore:
    kind = "firebase"
    supports_password_reset = True
    _IDENTITY = "https://identitytoolkit.googleapis.com/v1/accounts:{}"

    def __init__(self, cfg: dict):
        self.api_key = cfg["web_api_key"]
        self.project_id = cfg["project_id"]
        self.label = f"Firebase · {self.project_id}"
        self.degraded_reason = None
        self._db = self._init_firestore(cfg)
        log.info("Firebase store ready (project=%s)", self.project_id)

    # --- setup ------------------------------------------------------
    def _init_firestore(self, cfg: dict):
        import firebase_admin
        from firebase_admin import credentials, firestore

        try:
            app = firebase_admin.get_app()
        except ValueError:
            if cfg.get("service_account_json"):
                cred = credentials.Certificate(json.loads(cfg["service_account_json"]))
            elif cfg.get("service_account_file") and os.path.exists(cfg["service_account_file"]):
                cred = credentials.Certificate(cfg["service_account_file"])
            else:
                cred = credentials.ApplicationDefault()  # Cloud Run runtime service account
            app = firebase_admin.initialize_app(cred, {"projectId": self.project_id})
        db = firestore.client(app)
        db.collection("_meta").document("health").get(timeout=15)  # fail fast if DB missing / no access
        return db

    # --- auth (Identity Toolkit REST) -------------------------------
    def _identity(self, action: str, payload: dict) -> dict:
        try:
            resp = requests.post(self._IDENTITY.format(action), params={"key": self.api_key}, json=payload, timeout=15)
        except requests.RequestException as exc:
            log.error("Firebase Auth unreachable: %s", type(exc).__name__)  # message would include the key param
            raise AuthError("The sign-in service is unreachable. Check your connection and try again.") from exc
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.ok:
            return data
        raw = str((data.get("error") or {}).get("message", f"HTTP_{resp.status_code}"))
        code = raw.split(" ", 1)[0].strip(":")
        log.warning("Firebase Auth %s rejected: %s", action, raw)
        if "API key not valid" in raw or code == "API_KEY_INVALID":
            raise AuthError("Firebase Web API key is invalid. Check FIREBASE_WEB_API_KEY in config.")
        raise AuthError(_FIREBASE_ERRORS.get(code, f"Sign-in failed ({code})."))

    def sign_up(self, email: str, password: str) -> User:
        email = _validate(email, password, signup=True)
        data = self._identity("signUp", {"email": email, "password": password, "returnSecureToken": True})
        user = User(data["localId"], data.get("email", email))
        self.update_profile(user.uid, {"email": user.email, "created_at": utcnow_iso()})
        return user

    def sign_in(self, email: str, password: str) -> User:
        email = _validate(email, password)
        data = self._identity("signInWithPassword", {"email": email, "password": password, "returnSecureToken": True})
        return User(data["localId"], data.get("email", email))

    def send_password_reset(self, email: str) -> None:
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise AuthError("Enter a valid email address.")
        self._identity("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email})

    # --- data (Firestore) -------------------------------------------
    def _user_doc(self, uid: str):
        return self._db.collection("users").document(uid)

    def add(self, uid: str, collection: str, data: dict) -> str:
        payload = {**data, "created_at": data.get("created_at") or utcnow_iso()}
        try:
            ref = self._user_doc(uid).collection(collection).document()
            ref.set(json.loads(json.dumps(payload, default=str)))  # plain JSON types only
            return ref.id
        except Exception as exc:
            raise StorageError(str(exc)) from exc

    def list(self, uid: str, collection: str, limit: int = 500) -> list[dict]:
        try:
            query = self._user_doc(uid).collection(collection).order_by("created_at", direction="DESCENDING").limit(limit)
            out = [{**(d.to_dict() or {}), "id": d.id} for d in query.stream()]
        except Exception as exc:
            raise StorageError(str(exc)) from exc
        out.reverse()
        return out

    def get_profile(self, uid: str) -> dict:
        try:
            snap = self._user_doc(uid).get()
            return snap.to_dict() or {}
        except Exception as exc:
            raise StorageError(str(exc)) from exc

    def update_profile(self, uid: str, data: dict) -> None:
        try:
            self._user_doc(uid).set(json.loads(json.dumps(data, default=str)), merge=True)
        except Exception as exc:
            raise StorageError(str(exc)) from exc


# ======================================================================
# Factory
# ======================================================================
def create_store(firebase_cfg: dict, local_path: str, allow_fallback: bool = True):
    if firebase_cfg.get("web_api_key") and firebase_cfg.get("project_id"):
        try:
            return FirebaseStore(firebase_cfg)
        except Exception as exc:  # missing package, DB not created, no IAM access...
            log.exception("Firebase is configured but unavailable")
            if not allow_fallback:
                raise
            reason = f"Firebase is configured but unavailable ({type(exc).__name__}: {str(exc)[:160]})."
            return LocalStore(local_path, degraded_reason=reason)
    return LocalStore(local_path)
