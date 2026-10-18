"""
Secure Shift - authentication and persistence.

Two interchangeable backends expose the same interface:

* FirestoreStore - Google Cloud Firestore for accounts and history. Authenticates with
                   Application Default Credentials (Cloud Run service account, or
                   `gcloud auth application-default login` on a laptop).
* LocalStore     - SQLite. Used for tests, or as a fallback when Firestore is unreachable.

Both store salted PBKDF2-SHA256 password hashes, never the password itself.

Data model (identical in both backends)
    accounts/{email}                 credentials: uid, email, pw_hash, salt, rounds, created_at
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

log = logging.getLogger("secure_shift.storage")

COLLECTIONS = ("artifacts", "audits", "messages", "events")
EMAIL_RE = re.compile(r"^[^@\s/]+@[^@\s/]+\.[^@\s/]{2,}$")  # no "/": the email is a Firestore document id
MIN_PASSWORD = 8
PBKDF2_ROUNDS = 310_000


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


def _hash_password(password: str, salt_hex: str, rounds: int = PBKDF2_ROUNDS) -> str:
    return _pbkdf2_sha256(password.encode(), bytes.fromhex(salt_hex), rounds).hex()


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
        return _hash_password(password, salt_hex)

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
        raise AuthError("Password reset is not available in this demo.")

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
# Cloud Firestore backend
# ======================================================================
class FirestoreStore:
    kind = "firestore"
    supports_password_reset = False
    ACCOUNTS = "accounts"
    USERS = "users"

    def __init__(self, project_id: str = "", database: str = "(default)"):
        from google.cloud import firestore

        # Blank project_id -> the project of the active credentials (Cloud Run: the service's own project).
        self._db = firestore.Client(project=project_id or None, database=database or "(default)")
        self.project_id = self._db.project
        self.database = database or "(default)"
        suffix = "" if self.database == "(default)" else f" / {self.database}"
        self.label = f"Firestore · {self.project_id}{suffix}"
        self.degraded_reason = None
        self._db.collection("_meta").document("health").get(timeout=15)  # fail fast if DB missing / no access
        log.info("Firestore store ready (project=%s, database=%s)", self.project_id, self.database)

    # --- auth -------------------------------------------------------
    def _account_doc(self, email: str):
        return self._db.collection(self.ACCOUNTS).document(email)

    def sign_up(self, email: str, password: str) -> User:
        email = _validate(email, password, signup=True)
        salt = secrets.token_hex(16)
        uid = uuid.uuid4().hex
        now = utcnow_iso()
        try:
            # create() fails if the document exists, so two sign-ups for one email can't both win.
            self._account_doc(email).create({
                "uid": uid, "email": email, "pw_hash": _hash_password(password, salt), "salt": salt,
                "kdf": "pbkdf2_sha256", "rounds": PBKDF2_ROUNDS, "created_at": now,
            })
        except Exception as exc:
            if type(exc).__name__ == "AlreadyExists":
                raise AuthError("An account with this email already exists. Sign in instead.") from None
            raise StorageError(str(exc)) from exc
        self.update_profile(uid, {"email": email, "created_at": now})
        return User(uid, email)

    def sign_in(self, email: str, password: str) -> User:
        email = _validate(email, password)
        try:
            snap = self._account_doc(email).get(timeout=15)
        except Exception as exc:
            raise StorageError(str(exc)) from exc
        rec = snap.to_dict() if snap.exists else None
        if not rec:
            _hash_password(password, "00" * 16)  # equalise timing so emails can't be enumerated
            raise AuthError("Incorrect email or password.")
        actual = _hash_password(password, rec["salt"], int(rec.get("rounds") or PBKDF2_ROUNDS))
        if not hmac.compare_digest(actual, rec["pw_hash"]):
            raise AuthError("Incorrect email or password.")
        return User(rec["uid"], rec["email"])

    def send_password_reset(self, email: str) -> None:
        raise AuthError("Password reset is not available in this demo.")

    # --- data -------------------------------------------------------
    def _user_doc(self, uid: str):
        return self._db.collection(self.USERS).document(uid)

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
def create_store(firestore_cfg: dict, local_path: str, allow_fallback: bool = True):
    if firestore_cfg.get("enabled"):
        try:
            return FirestoreStore(firestore_cfg.get("project_id", ""), firestore_cfg.get("database", "(default)"))
        except Exception as exc:  # missing package, no credentials, DB not created, no IAM access...
            log.exception("Firestore is configured but unavailable")
            if not allow_fallback:
                raise
            reason = f"Firestore is configured but unavailable ({type(exc).__name__}: {str(exc)[:160]})."
            return LocalStore(local_path, degraded_reason=reason)
    return LocalStore(local_path)
