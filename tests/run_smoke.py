"""
End-to-end smoke test: executes the real app.py through every user journey.
    python tests/run_smoke.py
"""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="secure_shift_test_")
os.environ["LOCAL_DB_PATH"] = os.path.join(TMP, "test.db")
os.environ.setdefault("LOG_FILE", os.path.join(ROOT, "logs", "secure_shift.log"))
os.environ["FIREBASE_WEB_API_KEY"] = ""
os.environ["FIREBASE_PROJECT_ID"] = ""

import fake_genai  # noqa: E402

fake_genai.install()
import fake_streamlit  # noqa: E402

H = fake_streamlit.H
APP = os.path.join(ROOT, "app.py")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def outputs(kind):
    return [o for o in H.out if o[0] == kind]


def ss():
    return H.state


def new_session():
    """Simulate a fresh browser tab (same database)."""
    H.state._d.clear()
    H.widget_ids.clear()
    H.callbacks.clear()


def scenario(fn):
    try:
        fn()
    except Exception as exc:
        check(f"{fn.__name__} raised no exception", False, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    return fn


# ----------------------------------------------------------------------
@scenario
def s01_login_gate():
    r = H.run(APP)
    check("Unauthenticated visit stops at the login gate", r == "stop")
    txt = H.text()
    check("Login card is titled 'Demo Login'", "Demo Login" in txt)
    check("Demo ribbon is shown", "Demo stage." in txt)
    check("Storage backend is the local demo store", "Local demo store" in txt)


@scenario
def s02_signup_validation():
    H.run(APP, clicks=["form_submit_button:Create account"], changes={"su_email": "not-an-email", "su_pw": "short"})
    check("Invalid email rejected on sign-up", any("valid email" in o[1] for o in outputs("error")))
    H.run(APP, clicks=["form_submit_button:Create account"], changes={"su_email": "judge@demo.io", "su_pw": "short"})
    check("Short password rejected on sign-up", any("at least 8" in o[1] for o in outputs("error")))


@scenario
def s03_signup_ok():
    r = H.run(APP, clicks=["form_submit_button:Create account"], changes={"su_email": "Judge@Demo.io", "su_pw": "CorrectHorse1"})
    check("Sign-up succeeds and opens the workspace", r == "ok" and ss().user and ss().user["email"] == "judge@demo.io")
    check("Workspace header rendered", "Shift-left regulatory gatekeeper" in H.text())
    check("Welcome toast shown", any("Account created" in o[1] for o in outputs("toast")))
    check("Sign-up event persisted", any(e["action"] == "signed_up" for e in ss().data["events"]))
    import auditor
    opts = auditor.model_options(fake_genai.AVAILABLE + ["gemini-3.8-live"])
    check("Model list = catalogue ∩ key (no Live/Gemma models)", "gemma-4-31b-it" not in opts and "gemini-3.8-live" not in opts and opts[0] == "gemini-3.8-flash", str(opts))
    check("gemini-3.8-flash is the default selection", ss().get("model_select") == "gemini-3.8-flash")
    check("Catalogue drops retired Gemini 1.5/2.0/2.5 models", not any(m.id.startswith(("gemini-1.5", "gemini-2.")) for m in auditor.MODEL_CATALOG))


@scenario
def s04_duplicate_signup():
    new_session()
    H.run(APP, clicks=["form_submit_button:Create account"], changes={"su_email": "judge@demo.io", "su_pw": "CorrectHorse1"})
    check("Duplicate account blocked", any("already exists" in o[1] for o in outputs("error")))


@scenario
def s05_signin_and_sample():
    H.run(APP, clicks=["form_submit_button:Sign in"], changes={"text_input:Email": "judge@demo.io", "text_input:Password": "CorrectHorse1"})
    check("Sign-in succeeds", ss().user is not None)
    H.run(APP, clicks=["sample_btn"])
    arts = ss().data["artifacts"]
    check("Sample artifact persisted", len(arts) == 1 and arts[0]["source"] == "sample")
    check("Sample becomes the active case", ss().active_artifact_id == arts[0]["id"])
    check("Run audit button enabled hint gone", "To run the audit" not in H.text())


@scenario
def s06_audit_with_failover():
    fake_genai.SCRIPT.clear()
    fake_genai.CALLS.clear()
    fake_genai.SCRIPT["gemini-3.8-flash"] = [("err", 429, "Quota exceeded for metric generate_content_free_tier_requests")]
    fake_genai.SCRIPT["gemini-3.6-flash"] = [("err", 503, "high demand"), ("err", 503, "high demand")]
    H.run(APP, clicks=["run_audit_btn"])
    audits = ss().data["audits"]
    check("Audit persisted after failover", len(audits) == 1)
    a = audits[0]
    check("Failover landed on gemini-3.5-flash-lite", a["model_used"] == "gemini-3.5-flash-lite", a.get("model_used"))
    check("503 was retried once before moving on", [c["model"] for c in fake_genai.CALLS] == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"],
          str([c["model"] for c in fake_genai.CALLS]))
    cfg = fake_genai.CALLS[-1]["config"]
    check("JSON schema enforced", cfg.get("response_mime_type") == "application/json" and "response_schema" in cfg)
    check("No temperature override on Gemini 3+", "temperature" not in cfg)
    r = a["result"]
    check("Verdict REJECTED", r["audit_status"] == "REJECTED")
    check("Bracketed control id normalised", r["findings"][2]["control_id"] == "SOC2-CC6.3")
    check("Lower-case verdict normalised", r["findings"][2]["verdict"] == "FAIL" and r["failed_count"] == 3)
    check("terraform -> hcl highlighting", r["findings"][1]["remediation_language"] == "hcl")
    check("Missing language guessed from code", r["findings"][2]["remediation_language"] in ("hcl", "text"))
    check("Failover event logged", any(e["action"] == "model_failover" for e in ss().data["events"]))
    check("Verdict card rendered", "REJECTED" in H.text() and "Control breakdown" in H.text())
    check("Failover toast shown", any("unavailable" in o[1] for o in outputs("toast")))


@scenario
def s07_chat():
    fake_genai.SCRIPT.clear()
    fake_genai.CALLS.clear()
    H.run(APP, chat="Why did CC6.1 fail?")
    msgs = ss().data["messages"]
    check("User + assistant messages persisted", [m["role"] for m in msgs] == ["user", "assistant"])
    check("Assistant reply rendered after rerun", "Finding SOC2-CC6.1" in H.text())
    contents = fake_genai.CALLS[-1]["contents"]
    check("Chat primer includes findings JSON", "Latest audit findings" in contents[0].parts[0].text)
    H.run(APP, chat="Verify this patch: ALTER TABLE x ADD COLUMN ssn_enc BYTEA;")
    check("History sent on follow-up turn", len(fake_genai.CALLS[-1]["contents"]) == 2 + 2 + 1)


@scenario
def s08_upload_and_switch():
    H.run(APP, changes={f"uploader_{ss().uploader_nonce}": fake_streamlit.FakeUploadedFile("infra.tf", b'resource "aws_s3_bucket" "b" {}')})
    arts = ss().data["artifacts"]
    check("Upload persisted as a new case", len(arts) == 2 and arts[-1]["name"] == "infra.tf")
    check("Uploaded file is active; chat thread empty", ss().active_artifact_id == arts[-1]["id"] and "Start the conversation" in H.text())
    first = arts[0]["id"]
    H.run(APP, changes={f"case_select_{ss().case_nonce}": first})
    check("Case switcher restores previous case", ss().active_artifact_id == first and "Finding SOC2-CC6.1" in H.text())
    big = fake_streamlit.FakeUploadedFile("huge.sql", b"x" * 500_000)
    H.run(APP, changes={f"uploader_{ss().uploader_nonce}": big})
    check("Oversized upload rejected", len(ss().data["artifacts"]) == 2 and any("limit" in o[1] for o in outputs("error")))


@scenario
def s09_new_case():
    H.run(APP, clicks=["new_case_btn"])
    check("New case clears the workspace", ss().active_artifact_id is None and "No audit has been run" in H.text())
    H.run(APP, changes={f"case_select_{ss().case_nonce}": ss().data["artifacts"][0]["id"]})
    check("Can switch back from a new case", ss().active_artifact_id == ss().data["artifacts"][0]["id"])


@scenario
def s10_history():
    H.run(APP, changes={"nav": "Audit history"})
    txt = H.text()
    check("History page lists the run", "Audit history" in txt and "ekyc_schema_vulnerable.sql" in txt)
    H.run(APP, changes={"hist_filter": "Approved"})
    check("Verdict filter works", "0 of 1 shown" in H.text())
    H.run(APP, changes={"hist_filter": "All"})
    aid = ss().data["audits"][0]["id"]
    H.run(APP, clicks=[f"open_{aid}"])
    check("'Open in workspace' navigates back", ss().nav == "Workspace" and "Shift-left regulatory gatekeeper" in H.text())


@scenario
def s11_activity_log():
    H.run(APP, changes={"nav": "Activity log"})
    txt = H.text()
    check("Activity log shows files", "Submitted ekyc_schema_vulnerable.sql" in txt and "Submitted infra.tf" in txt)
    check("Activity log shows full chat", "Why did CC6.1 fail?" in txt and "Finding SOC2-CC6.1" in txt)
    check("Activity log shows audits and sign-ins", "Audit · ekyc_schema_vulnerable.sql" in txt and "Signed in" in txt)
    check("File content viewable in log", any(o[0] == "code" and "ssn_plaintext" in o[1] for o in H.out))
    H.run(APP, changes={"log_q": "patch"})
    check("Search filters entries", "Verify this patch" in H.text() and "Submitted infra.tf" not in H.text())
    H.run(APP, changes={"log_q": "", "log_types": ["Files"]})
    check("Type filter shows only files", "Submitted infra.tf" in H.text() and "Why did CC6.1 fail?" not in H.text())
    H.run(APP, changes={"log_types": ["Files", "Audits", "Chat", "Account & system"], "log_order": "Oldest first"})
    check("Oldest-first ordering renders", "Account created" in H.text())


@scenario
def s12_signout_restore():
    H.run(APP, clicks=["signout_btn"])
    check("Sign-out returns to the login gate", ss().user is None and "Demo Login" in H.text())
    new_session()
    H.run(APP, clicks=["form_submit_button:Sign in"], changes={"text_input:Email": "judge@demo.io", "text_input:Password": "wrong-password"})
    check("Wrong password rejected generically", any("Incorrect email or password" in o[1] for o in outputs("error")))
    H.run(APP, clicks=["form_submit_button:Sign in"], changes={"text_input:Email": "judge@demo.io", "text_input:Password": "CorrectHorse1"})
    d = ss().data
    check("History restored from the database on sign-in", len(d["audits"]) == 1 and len(d["messages"]) == 4 and len(d["artifacts"]) == 2,
          f"audits={len(d['audits'])} msgs={len(d['messages'])} files={len(d['artifacts'])}")
    check("Last active case restored", ss().active_artifact_id == d["artifacts"][0]["id"])
    check("Restore toast shown", any("Restored 1 audits, 4 messages and 2 files" in o[1] for o in outputs("toast")))


@scenario
def s13_all_models_fail():
    fake_genai.SCRIPT.clear()
    fake_genai.SCRIPT["*"] = [("err", 429, "Quota exceeded")]
    n = len(ss().data["audits"])
    H.run(APP, clicks=["run_audit_btn"])
    check("All-models-exhausted shows a clear quota error", any("quota exhausted" in o[1].lower() for o in outputs("error")))
    check("Failed audit not stored as a verdict", len(ss().data["audits"]) == n)
    check("Failure recorded in the activity trail", any(e["action"] == "audit_failed" for e in ss().data["events"]))
    fake_genai.SCRIPT.clear()
    fake_genai.SCRIPT["*"] = [("err", 400, "API key not valid. Please pass a valid API key.")]
    H.run(APP, clicks=["run_audit_btn"])
    check("Invalid API key stops immediately with guidance", any("API key was rejected" in o[1] for o in outputs("error")))
    fake_genai.SCRIPT.clear()


@scenario
def s14_lockout():
    H.run(APP, clicks=["signout_btn"])
    new_session()
    for _ in range(5):
        H.run(APP, clicks=["form_submit_button:Sign in"], changes={"text_input:Email": "judge@demo.io", "text_input:Password": "nope-nope"})
    H.run(APP, clicks=["form_submit_button:Sign in"], changes={"text_input:Email": "judge@demo.io", "text_input:Password": "CorrectHorse1"})
    check("Brute-force lockout after 5 failures", ss().user is None and any("Too many failed attempts" in o[1] for o in outputs("error")))


@scenario
def s15_no_api_key():
    import config
    saved = config.GEMINI_API_KEY
    config.GEMINI_API_KEY = ""
    new_session()
    H.state._d["auth_locked_until"] = 0.0
    H.run(APP, clicks=["form_submit_button:Sign in"], changes={"text_input:Email": "judge@demo.io", "text_input:Password": "CorrectHorse1"})
    check("Missing API key disables audit with a hint", "To run the audit, add an API key." in H.text())
    check("Sidebar flags missing key", "API key required" in H.text())
    H.run(APP, changes={"api_key_override": "session-key"})
    check("Session key override enables audits", "To run the audit" not in H.text() and "Session key override" in H.text())
    config.GEMINI_API_KEY = saved


@scenario
def s16_storage_units():
    import storage
    s = storage.LocalStore(os.path.join(TMP, "unit.db"))
    u = s.sign_up("A@B.co", "longenough1")
    check("Emails normalised to lower-case", u.email == "a@b.co")
    check("Passwords are hashed, never stored in clear", "longenough1" not in open(os.path.join(TMP, "unit.db"), "rb").read().decode("latin1"))
    s.add(u.uid, "events", {"action": "x", "created_at": "2026-01-01T00:00:00.000000Z"})
    s.add(u.uid, "events", {"action": "y", "created_at": "2026-01-02T00:00:00.000000Z"})
    check("list() returns oldest-first", [e["action"] for e in s.list(u.uid, "events")] == ["x", "y"])
    check("list() limit keeps the newest", [e["action"] for e in s.list(u.uid, "events", limit=1)] == ["y"])
    s.update_profile(u.uid, {"active_artifact_id": "abc"})
    check("Profile merge", s.get_profile(u.uid).get("active_artifact_id") == "abc" and s.get_profile(u.uid).get("email") == "a@b.co")
    check("mask_email hides the local part", storage.mask_email("jane.doe@acme.com") == "j***@acme.com")


@scenario
def s17_firebase_backend():
    """Exercise FirebaseStore against fake firebase_admin + Identity Toolkit."""
    import types as t
    import storage

    docs = {}

    class Snap:
        def __init__(self, path):
            self.id = path.split("/")[-1]
            self._p = path

        def to_dict(self):
            return docs.get(self._p)

    class Doc:
        def __init__(self, path):
            self.path = path
            self.id = path.split("/")[-1]

        def collection(self, name):
            return Col(f"{self.path}/{name}")

        def set(self, data, merge=False):
            docs[self.path] = {**(docs.get(self.path, {}) if merge else {}), **data}

        def get(self, timeout=None):
            return Snap(self.path)

    class Query:
        def __init__(self, col, field, direction, n=None):
            self.col, self.field, self.direction, self.n = col, field, direction, n

        def limit(self, n):
            return Query(self.col, self.field, self.direction, n)

        def stream(self):
            items = [(p, d) for p, d in docs.items() if p.rsplit("/", 1)[0] == self.col.path]
            items.sort(key=lambda x: x[1][self.field], reverse=self.direction == "DESCENDING")
            return [Snap(p) for p, _ in items[: self.n]]

    class Col:
        def __init__(self, path):
            self.path = path

        def document(self, did=None):
            import uuid
            return Doc(f"{self.path}/{did or uuid.uuid4().hex[:20]}")

        def order_by(self, field, direction="ASCENDING"):
            return Query(self, field, direction)

    class DB(Col):
        def __init__(self):
            super().__init__("")

        def collection(self, name):
            return Col(name)

    fa = t.ModuleType("firebase_admin")
    fa.get_app = lambda: (_ for _ in ()).throw(ValueError("no app"))
    fa.initialize_app = lambda cred, opts: "app"
    cred_mod = t.ModuleType("firebase_admin.credentials")
    cred_mod.Certificate = lambda x: ("cert", x)
    cred_mod.ApplicationDefault = lambda: ("adc",)
    fs_mod = t.ModuleType("firebase_admin.firestore")
    fs_mod.client = lambda app: DB()
    fa.credentials, fa.firestore = cred_mod, fs_mod
    sys.modules.update({"firebase_admin": fa, "firebase_admin.credentials": cred_mod, "firebase_admin.firestore": fs_mod})

    calls = []

    class R:
        def __init__(self, ok, data, status=200):
            self.ok, self._d, self.status_code, self.content = ok, data, status, b"x"

        def json(self):
            return self._d

    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((url.rsplit(":", 1)[-1], params, json))
        if url.endswith("signUp"):
            return R(True, {"localId": "fbuid123", "email": json["email"]})
        if url.endswith("signInWithPassword"):
            if json["password"] == "good-password":
                return R(True, {"localId": "fbuid123", "email": json["email"]})
            return R(False, {"error": {"message": "INVALID_LOGIN_CREDENTIALS"}}, 400)
        if url.endswith("sendOobCode"):
            return R(True, {"email": json["email"]})
        return R(False, {"error": {"message": "OPERATION_NOT_ALLOWED"}}, 400)

    real_post = storage.requests.post
    storage.requests.post = fake_post
    try:
        fs = storage.create_store({"web_api_key": "AIzaFAKE", "project_id": "demo-proj", "service_account_file": "", "service_account_json": ""}, os.path.join(TMP, "fb_fallback.db"))
        check("Firebase backend selected when configured", fs.kind == "firebase" and fs.label == "Firebase · demo-proj")
        u = fs.sign_up("New@User.com", "good-password")
        check("Firebase sign-up uses Identity Toolkit signUp", calls[-1][0] == "signUp" and calls[-1][1] == {"key": "AIzaFAKE"} and u.uid == "fbuid123")
        try:
            fs.sign_in("new@user.com", "bad")
            check("Firebase bad password mapped", False)
        except storage.AuthError as e:
            check("Firebase INVALID_LOGIN_CREDENTIALS mapped to friendly text", str(e) == "Incorrect email or password.")
        u2 = fs.sign_in("new@user.com", "good-password")
        fs.add(u2.uid, "messages", {"role": "user", "content": "a", "created_at": "2026-10-18T10:00:00.000000Z"})
        fs.add(u2.uid, "messages", {"role": "assistant", "content": "b", "created_at": "2026-10-18T10:00:01.000000Z"})
        got = fs.list(u2.uid, "messages")
        check("Firestore list returns oldest-first with ids", [m["content"] for m in got] == ["a", "b"] and all("id" in m for m in got))
        check("Firestore path is users/{uid}/messages", any(p.startswith("users/fbuid123/messages/") for p in docs))
        fs.update_profile(u2.uid, {"active_artifact_id": "z"})
        check("Firestore profile merge keeps email", fs.get_profile(u2.uid).get("email") == "new@user.com" and fs.get_profile(u2.uid)["active_artifact_id"] == "z")
        fs.send_password_reset("new@user.com")
        check("Password reset uses sendOobCode", calls[-1][0] == "sendOobCode" and calls[-1][2]["requestType"] == "PASSWORD_RESET")

        fs_mod.client = lambda app: (_ for _ in ()).throw(RuntimeError("The database (default) does not exist"))
        degraded = storage.create_store({"web_api_key": "AIzaFAKE", "project_id": "demo-proj"}, os.path.join(TMP, "fb_fallback.db"))
        check("Broken Firebase falls back to local store with a visible reason", degraded.kind == "local" and "does not exist" in (degraded.degraded_reason or ""))
    finally:
        storage.requests.post = real_post
        for m in ("firebase_admin", "firebase_admin.credentials", "firebase_admin.firestore"):
            sys.modules.pop(m, None)


# ----------------------------------------------------------------------
passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n{passed}/{len(RESULTS)} checks passed across {H.runs} script runs")
sys.exit(0 if passed == len(RESULTS) else 1)
