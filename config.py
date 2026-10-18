"""
Secure Shift - central configuration.

Every setting can come from an environment variable (Cloud Run, Secret Manager)
or from a local `.env` file next to this module. Values typed directly into the
FIREBASE block below also work, but env vars always win.
"""

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = "2.0.0-demo"


def _load_dotenv() -> None:
    """Minimal .env loader (no extra dependency). Existing env vars are never overwritten."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# ------------------------------------------------------------------
# Environment
# ------------------------------------------------------------------
ON_CLOUD_RUN = bool(os.getenv("K_SERVICE"))
DEMO_MODE = _bool("DEMO_MODE", True)  # shows the "Demo" ribbon and "Demo Login" title

# ------------------------------------------------------------------
# Gemini
# ------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-3.8-flash")

# ------------------------------------------------------------------
# FIREBASE  <<<  paste your project values here (or set the env vars)  >>>
# ------------------------------------------------------------------
# As soon as `web_api_key` and `project_id` are filled in, the app switches
# from the local demo store to Firebase Authentication + Cloud Firestore.
FIREBASE = {
    # Firebase console > Project settings > General > "Web API Key"
    "web_api_key": os.getenv("FIREBASE_WEB_API_KEY", "AIzaSyAJuBq6L6CuJgMVy42QTeZEFBnirpAU-jY"),
    # Firebase console > Project settings > General > "Project ID"
    "project_id": os.getenv("FIREBASE_PROJECT_ID", "shift-3cd38"),
    # Local runs only: path to a service-account key (Project settings > Service accounts).
    # On Cloud Run in the same project, leave it absent - the runtime service account is used.
    "service_account_file": os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_FILE", str(BASE_DIR / "firebase-service-account.json")
    ),
    # Alternative to the file: the raw JSON (e.g. mounted from Secret Manager).
    "service_account_json": os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", ""),
}


def firebase_configured() -> bool:
    return bool(FIREBASE["web_api_key"] and FIREBASE["project_id"])


# If Firebase is configured but unreachable, keep the demo running on the local store
# (with a visible warning) instead of locking everyone out.
ALLOW_LOCAL_FALLBACK = _bool("ALLOW_LOCAL_FALLBACK", True)

# ------------------------------------------------------------------
# Local demo store (used until Firebase is configured)
# ------------------------------------------------------------------
LOCAL_DB_PATH = os.getenv("LOCAL_DB_PATH", str(BASE_DIR / "data" / "secure_shift_demo.db"))

# ------------------------------------------------------------------
# Limits
# ------------------------------------------------------------------
MAX_ARTIFACT_BYTES = int(os.getenv("MAX_ARTIFACT_BYTES", str(400_000)))  # Firestore doc limit is 1 MiB
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "500"))  # records per collection loaded at sign-in
CHAT_CONTEXT_TURNS = int(os.getenv("CHAT_CONTEXT_TURNS", "30"))
ALLOWED_EXTENSIONS = ["tf", "tfvars", "hcl", "sql", "yaml", "yml", "json", "txt", "md"]

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# Local runs also write a rotating log file; Cloud Run streams to Cloud Logging instead.
LOG_FILE = os.getenv("LOG_FILE", "" if ON_CLOUD_RUN else str(BASE_DIR / "logs" / "secure_shift.log"))


class _CloudLoggingFormatter(logging.Formatter):
    """One JSON object per line - Cloud Logging parses `severity` and `message`."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
        }
        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    """Idempotent - Streamlit re-runs the script on every interaction."""
    logger = logging.getLogger("secure_shift")
    if getattr(logger, "_secure_shift_configured", False):
        return
    logger.setLevel(LOG_LEVEL)
    logger.propagate = False

    stream = logging.StreamHandler(sys.stdout)
    if ON_CLOUD_RUN:
        stream.setFormatter(_CloudLoggingFormatter())
    else:
        stream.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
    logger.addHandler(stream)

    if LOG_FILE:
        try:
            Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
            logger.addHandler(fh)
        except OSError as exc:  # read-only filesystem etc.
            logger.warning("File logging disabled: %s", exc)

    logger._secure_shift_configured = True  # type: ignore[attr-defined]
    logger.info(
        "Logging ready (version=%s, cloud_run=%s, firebase=%s)", APP_VERSION, ON_CLOUD_RUN, firebase_configured()
    )
