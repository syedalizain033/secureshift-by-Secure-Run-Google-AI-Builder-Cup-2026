"""
AI Builders Cup
Secure Shift - Autonomous AI-Driven Lead Auditor & Shift-Left GRC Gateway
Reference target: IdentityAI (eKYC platform)
Regulatory standards: SOC 2 Type II, CCPA, GLBA

Run locally:   streamlit run app.py
Deploy:        ./deploy.sh   (Google Cloud Run)
"""

import hashlib
import html
import inspect
import json
import logging
import uuid
from datetime import datetime, timezone

import streamlit as st

import auditor
import config
from storage import COLLECTIONS, AuthError, create_store, mask_email, utcnow_iso

config.setup_logging()
log = logging.getLogger("secure_shift.app")

st.set_page_config(
    page_title="Secure Shift | GRC Gateway",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="auto",  # open on desktop, collapsed on phones
)

# ======================================================================
# 1. DESIGN SYSTEM
# ======================================================================
TOKENS = {
    "navy-950": "#071A33", "navy-900": "#0B2545", "navy-800": "#13315C", "navy-700": "#1F4177", "navy-600": "#2B4F86",
    "blue-600": "#1D5FD1", "blue-700": "#1649A6", "blue-50": "#EEF4FF", "accent": "#6EA8FF",
    "bg": "#F4F6FA", "surface": "#FFFFFF", "surface-2": "#F8FAFC",
    "border": "#DDE3EC", "border-strong": "#B8C2D1",
    "text": "#0F1B2D", "text-muted": "#526077", "text-subtle": "#6B778C",
    "pass": "#157A4A", "pass-bg": "#E8F5EE", "pass-bd": "#BFE3CE",
    "fail": "#B42318", "fail-bg": "#FDEDEB", "fail-bd": "#F4C7C2",
    "warn": "#8A5200", "warn-bg": "#FFF5DD", "warn-bd": "#F2D9A4",
    "info": "#1D5FD1", "info-bg": "#EEF4FF", "info-bd": "#C9DAFB",
    "violet": "#6E56CF",
}
ROOT_CSS = ":root{" + "".join(f"--{k}:{v};" for k, v in TOKENS.items()) + "}"

CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
html, body, .stApp, .stApp button, .stApp input, .stApp textarea, .stMarkdown {font-family:'IBM Plex Sans',-apple-system,'Segoe UI',Roboto,sans-serif;}
code, pre, kbd, .mono {font-family:'IBM Plex Mono',ui-monospace,SFMono-Regular,monospace !important;}
[data-testid="stIconMaterial"] {font-family:'Material Symbols Rounded' !important;}
.stApp {background:radial-gradient(1100px 420px at 85% -140px, rgba(29,95,209,.09), transparent 70%), var(--bg); color:var(--text);}
[data-testid="stHeader"] {background:transparent;}
[data-testid="stDecoration"] {display:none;}
footer, #MainMenu {visibility:hidden;}
.block-container, [data-testid="stMainBlockContainer"] {padding-top:3rem; padding-bottom:3rem; max-width:1360px;}
h1,h2,h3,h4 {color:var(--navy-900); letter-spacing:-0.012em; font-weight:600;}
.stApp :focus-visible {outline:2px solid var(--blue-600); outline-offset:2px;}

/* ---------- Demo ribbon ---------- */
.demo-banner {display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:8px 14px; margin:0 0 18px; border-radius:8px;
  background:var(--warn-bg); border:1px solid var(--warn-bd); color:#5C3A00; font-size:.85rem;}
.demo-tag {font-weight:700; font-size:.7rem; letter-spacing:.08em; padding:3px 8px; border-radius:4px; background:var(--warn); color:#fff;}
.demo-meta {margin-left:auto; font-size:.78rem; color:#7A5410; display:flex; gap:6px; align-items:center;}
.demo-meta .dot {width:7px; height:7px; border-radius:50%; background:var(--pass); display:inline-block;}
.demo-meta .dot.degraded {background:var(--fail);}

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] {background:linear-gradient(180deg,var(--navy-900) 0%,var(--navy-950) 100%); border-right:1px solid var(--navy-700);}
section[data-testid="stSidebar"] > div {background:transparent;}
section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] * {color:#DCE5F2;}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"], section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {color:#9FB3D1 !important;}
section[data-testid="stSidebar"] [data-baseweb="input"], section[data-testid="stSidebar"] [data-baseweb="input"] > div,
section[data-testid="stSidebar"] [data-baseweb="select"] > div {background:var(--navy-800) !important; border-color:var(--navy-700) !important;}
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] [data-baseweb="select"] * {color:#fff !important; -webkit-text-fill-color:#fff;}
section[data-testid="stSidebar"] [data-baseweb="select"] svg {fill:#fff;}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"], section[data-testid="stSidebar"] [data-testid="stTextInputRootElement"] {background:var(--navy-800) !important; border-color:var(--navy-700) !important;}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] svg {fill:#fff; color:#fff;}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:not([data-testid]) {display:none;}
section[data-testid="stSidebar"] button[kind="headerNoPadding"], section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] * {color:#DCE5F2 !important;}
section[data-testid="stSidebar"] [role="radiogroup"] {gap:2px;}
section[data-testid="stSidebar"] [role="radiogroup"] label {width:100%; padding:9px 12px; border-radius:6px; border-left:3px solid transparent; cursor:pointer; transition:background .15s;}
section[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {position:absolute; opacity:0; width:0; height:0; overflow:hidden;}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {background:var(--navy-800);}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background:var(--navy-800); border-left-color:var(--accent);}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {color:#fff; font-weight:600;}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:focus-visible) {outline:2px solid var(--accent);}
section[data-testid="stSidebar"] [data-testid="stExpander"] details {background:rgba(255,255,255,.03); border:1px solid var(--navy-700); border-radius:8px;}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary * {color:#DCE5F2 !important;}
section[data-testid="stSidebar"] .stButton button {background:transparent; color:#DCE5F2; border:1px solid var(--navy-600);}
section[data-testid="stSidebar"] .stButton button:hover {background:var(--navy-800); color:#fff; border-color:var(--accent);}
.brand {display:flex; align-items:center; gap:10px; padding:2px 0 18px;}
.brand-mark {width:36px; height:36px; border-radius:9px; background:linear-gradient(135deg,#2E74F0,#1D5FD1); display:flex; align-items:center; justify-content:center; box-shadow:0 4px 14px rgba(29,95,209,.45);}
.brand-name {font-weight:600; font-size:1.05rem; color:#fff; line-height:1.2; display:flex; align-items:center; gap:8px;}
.brand-sub {font-size:.75rem; color:#9FB3D1;}
.pill-demo {font-size:.6rem; font-weight:700; letter-spacing:.08em; padding:2px 6px; border-radius:4px; background:#F2B544; color:#3A2600 !important;}
.user-card {display:flex; align-items:center; gap:10px; padding:10px 12px; background:rgba(255,255,255,.04); border:1px solid var(--navy-700); border-radius:10px; margin:0 0 16px;}
.avatar {width:32px; height:32px; border-radius:50%; background:linear-gradient(135deg,#3B82F6,#1D5FD1); color:#fff !important; font-weight:600; font-size:.8rem; display:flex; align-items:center; justify-content:center; flex-shrink:0;}
.user-email {color:#fff !important; font-size:.84rem; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:180px;}
.user-sub {font-size:.72rem; color:#9FB3D1 !important;}
.side-label {font-size:.7rem; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:#8EA3C4; margin:22px 0 6px;}
.side-foot {font-size:.76rem; color:#9FB3D1; line-height:1.7; border-top:1px solid var(--navy-700); margin-top:22px; padding-top:14px;}
.side-foot b {color:#DCE5F2;}

/* ---------- Page + cards ---------- */
.page-header h1 {font-size:1.6rem; margin:0;}
.page-header p {color:var(--text-muted); margin:4px 0 18px; max-width:72ch;}
[class*="st-key-card_"] {background:var(--surface); border:1px solid var(--border) !important; border-radius:10px; padding:20px 22px !important; box-shadow:0 1px 2px rgba(16,24,40,.05);}
.card-title {font-size:1rem; font-weight:600; color:var(--navy-900);}
.card-caption {font-size:.85rem; color:var(--text-muted); margin:2px 0 14px;}
.hint {font-size:.82rem; color:var(--text-muted);}
.meta-line {display:flex; flex-wrap:wrap; gap:8px; align-items:center; font-size:.82rem; color:var(--text-muted); margin:4px 0 8px;}

/* ---------- Stepper ---------- */
.stepper {display:flex; gap:8px; flex-wrap:wrap; margin:0 0 20px;}
.step {display:flex; align-items:center; gap:8px; flex:1; min-width:170px; padding:10px 14px; background:var(--surface); border:1px solid var(--border); border-radius:8px; font-size:.875rem; color:var(--text-muted);}
.step-dot {width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:.75rem; font-weight:600; background:#E7ECF3; color:var(--text-muted);}
.step.current {border-color:var(--blue-600); color:var(--navy-900); font-weight:500; box-shadow:0 0 0 3px rgba(29,95,209,.08);}
.step.current .step-dot {background:var(--blue-600); color:#fff;}
.step.done {color:var(--text);}
.step.done .step-dot {background:var(--pass); color:#fff;}

/* ---------- Chips ---------- */
.chip {display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:4px; font-size:.75rem; font-weight:600; border:1px solid transparent; white-space:nowrap; line-height:1.6;}
.chip::before {content:""; width:6px; height:6px; border-radius:50%; background:currentColor;}
.stApp .chip-pass {color:var(--pass); background:var(--pass-bg); border-color:var(--pass-bd);}
.stApp .chip-fail {color:var(--fail); background:var(--fail-bg); border-color:var(--fail-bd);}
.stApp .chip-warn {color:var(--warn); background:var(--warn-bg); border-color:var(--warn-bd);}
.stApp .chip-info {color:var(--info); background:var(--info-bg); border-color:var(--info-bd);}
.stApp .chip-violet {color:var(--violet); background:#F1EEFC; border-color:#D9D1F7;}
.stApp .chip-crit {color:#fff; background:var(--fail); border-color:var(--fail);}
.stApp .chip-neutral {color:var(--text-muted); background:#EEF1F6; border-color:var(--border);}

/* ---------- Verdict ---------- */
.verdict {display:flex; align-items:center; gap:14px; padding:14px 16px; border-radius:10px; border:1px solid; margin:6px 0 14px;}
.verdict.is-fail {background:var(--fail-bg); border-color:var(--fail-bd);}
.verdict.is-pass {background:var(--pass-bg); border-color:var(--pass-bd);}
.verdict-icon {width:38px; height:38px; border-radius:50%; display:flex; align-items:center; justify-content:center; flex-shrink:0;}
.verdict.is-fail .verdict-icon {background:var(--fail);}
.verdict.is-pass .verdict-icon {background:var(--pass);}
.verdict-title {font-weight:700; font-size:1.05rem; letter-spacing:.02em;}
.verdict.is-fail .verdict-title {color:var(--fail);}
.verdict.is-pass .verdict-title {color:var(--pass);}
.verdict-sub {font-size:.84rem; color:var(--text-muted);}
.kpis {display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:14px;}
.kpi {border:1px solid var(--border); border-radius:8px; padding:11px 13px; background:var(--surface);}
.kpi-label {font-size:.74rem; color:var(--text-muted); margin-bottom:4px;}
.kpi-value {font-size:1.25rem; font-weight:600; color:var(--navy-900); line-height:1.3;}
.kpi-value small {font-size:.75rem; font-weight:500; color:var(--text-muted);}
.summary {background:var(--surface-2); border:1px solid var(--border); border-radius:8px; padding:12px 14px; font-size:.9rem; line-height:1.55; margin-bottom:8px;}
.finding {border:1px solid var(--border); border-left:4px solid var(--border-strong); border-radius:8px; padding:12px 14px; margin:10px 0 6px; background:var(--surface);}
.finding.is-pass {border-left-color:var(--pass);}
.finding.is-fail {border-left-color:var(--fail);}
.finding-head {display:flex; align-items:center; gap:8px; flex-wrap:wrap;}
.finding-title {font-weight:600; color:var(--navy-900); flex:1; min-width:180px;}
.finding p {margin:8px 0 0; font-size:.9rem; line-height:1.55;}
.mono {font-size:.78rem; color:var(--text-muted);}
.empty {text-align:center; padding:34px 16px; color:var(--text-muted);}
.empty strong {display:block; color:var(--navy-900); font-size:1rem; margin-bottom:4px;}

/* ---------- Ledger table ---------- */
.table-wrap {overflow-x:auto; border:1px solid var(--border); border-radius:8px;}
table.ledger {width:100%; border-collapse:collapse; font-size:.86rem; background:var(--surface);}
table.ledger th {text-align:left; font-weight:600; color:var(--text-muted); font-size:.74rem; text-transform:uppercase; letter-spacing:.04em; padding:10px 12px; background:var(--surface-2); border-bottom:1px solid var(--border);}
table.ledger td {padding:10px 12px; border-bottom:1px solid #EEF1F6; color:var(--text); white-space:nowrap;}
table.ledger tr:last-child td {border-bottom:none;}
table.ledger tr:hover td {background:#FAFBFD;}

/* ---------- Chat ---------- */
[data-testid="stChatMessage"] {background:transparent; padding:.55rem .35rem;}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {background:var(--blue-50); border:1px solid #DCE7FB; border-radius:10px; padding:.6rem .8rem;}
.msg-meta {font-size:.72rem; color:var(--text-subtle); margin-top:2px;}
.st-key-suggest button {border-radius:999px !important; font-size:.8rem !important; padding:.2rem .85rem !important; min-height:0 !important; background:var(--surface-2) !important;}

/* ---------- Activity log ---------- */
.st-key-logwindow {background:var(--surface-2); border-radius:10px;}
[class*="st-key-entry_"] {background:var(--surface); border:1px solid var(--border); border-left:3px solid var(--border-strong); border-radius:8px; padding:10px 14px !important; gap:.4rem !important;}
[class*="st-key-entry_file"] {border-left-color:var(--violet);}
[class*="st-key-entry_audit"] {border-left-color:var(--navy-700);}
[class*="st-key-entry_user"] {border-left-color:var(--blue-600);}
[class*="st-key-entry_assistant"] {border-left-color:var(--pass);}
[class*="st-key-entry_event"] {background:#FBFCFE;}
.log-head {display:flex; align-items:center; gap:10px; flex-wrap:wrap; font-size:.85rem;}
.log-time {font-family:'IBM Plex Mono',monospace; font-size:.74rem; color:var(--text-subtle); min-width:132px;}
.log-title {font-weight:600; color:var(--navy-900);}
.log-meta {color:var(--text-muted); font-size:.78rem;}
.log-stats {display:flex; gap:16px; flex-wrap:wrap; font-size:.82rem; color:var(--text-muted); margin:2px 0 10px;}
.log-stats b {color:var(--navy-900);}

/* ---------- Widgets ---------- */
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button {border-radius:7px; font-weight:500; border:1px solid var(--border-strong); background:#fff; color:var(--navy-900); transition:background .15s, border-color .15s;}
.stButton button:hover, .stDownloadButton button:hover {border-color:var(--blue-600); color:var(--blue-700); background:#F3F7FF;}
.stApp button[kind="primary"], .stApp button[data-testid="stBaseButton-primary"], .stApp button[kind="primaryFormSubmit"], .stApp button[data-testid="stBaseButton-primaryFormSubmit"] {background:var(--blue-600); border-color:var(--blue-600); color:#fff; font-weight:600;}
.stApp button[kind="primary"]:hover, .stApp button[data-testid="stBaseButton-primary"]:hover, .stApp button[kind="primaryFormSubmit"]:hover, .stApp button[data-testid="stBaseButton-primaryFormSubmit"]:hover {background:var(--blue-700); border-color:var(--blue-700); color:#fff;}
.stApp button:disabled {background:#EEF1F6 !important; border-color:var(--border) !important; color:#8A96A8 !important;}
[data-testid="stFileUploaderDropzone"] {background:var(--surface-2); border:1px dashed var(--border-strong); border-radius:8px;}
/* Form fields: white surface + visible border (clearer affordance than tinted fills) */
[data-testid="stMain"] [data-testid="stTextInputRootElement"], [data-testid="stMain"] [data-testid="stSelectbox"] [role="group"],
[data-testid="stMain"] [data-testid="stChatInput"] > div, [data-testid="stMain"] [data-baseweb="input"],
[data-testid="stMain"] [data-baseweb="select"] > div {background:#fff !important; border:1px solid var(--border-strong) !important;}
[data-testid="stMain"] [data-testid="stTextInputRootElement"]:focus-within, [data-testid="stMain"] [data-testid="stSelectbox"] [role="group"]:focus-within,
[data-testid="stMain"] [data-testid="stChatInput"] > div:focus-within {border-color:var(--blue-600) !important; box-shadow:0 0 0 3px rgba(29,95,209,.12);}
[data-testid="stExpander"] details {border:1px solid var(--border); border-radius:8px; background:#fff;}
.stTabs [data-baseweb="tab-list"] {gap:6px; border-bottom:1px solid var(--border);}
.stTabs [data-baseweb="tab"] {font-weight:500; padding:8px 4px;}

@media (max-width:1100px) {.kpis {grid-template-columns:repeat(2,1fr);}}
@media (prefers-reduced-motion:reduce) {* {transition:none !important;}}
"""

AUTH_CSS = """
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"], [data-testid="collapsedControl"] {display:none !important;}
.block-container, [data-testid="stMainBlockContainer"] {max-width:1180px;}
.auth-panel {position:relative; overflow:hidden; min-height:590px; border-radius:16px; padding:34px 36px 30px; color:#E6EEF9; display:flex; flex-direction:column; gap:26px;
  background:
    radial-gradient(620px 320px at 110% -10%, rgba(110,168,255,.30), transparent 60%),
    radial-gradient(520px 360px at -20% 120%, rgba(29,95,209,.50), transparent 60%),
    linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px) 0 0/28px 28px,
    linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px) 0 0/28px 28px,
    linear-gradient(160deg, #0B2545 0%, #071A33 100%);
  box-shadow:0 24px 60px -24px rgba(7,26,51,.55);}
.auth-panel .brand {padding:0;}
.auth-hero h1 {color:#fff; font-size:2.05rem; line-height:1.18; margin:8px 0 12px; font-weight:600; letter-spacing:-.02em;}
.auth-hero p {color:#B9C8DE; font-size:1rem; line-height:1.6; max-width:46ch; margin:0;}
.auth-points {list-style:none; padding:0; margin:0; display:grid; gap:13px;}
.auth-points li {display:flex; gap:10px; align-items:flex-start; color:#DCE5F2; font-size:.93rem; line-height:1.45; margin:0 !important; padding:0 !important;}
.auth-points svg {flex-shrink:0; margin-top:2px;}
.auth-badges {margin-top:auto; display:flex; gap:8px; flex-wrap:wrap;}
.auth-badges span {font-size:.72rem; font-weight:600; letter-spacing:.04em; padding:5px 11px; border-radius:999px; border:1px solid rgba(255,255,255,.18); color:#DCE5F2; background:rgba(255,255,255,.05);}
[class*="st-key-card_auth"] {padding:30px 32px !important; border-radius:16px; box-shadow:0 14px 36px -14px rgba(16,24,40,.20); margin-top:10px;}
.auth-head h2 {margin:10px 0 4px; font-size:1.55rem;}
.auth-head p {color:var(--text-muted); margin:0 0 8px; font-size:.92rem;}
.auth-head .chip {font-size:.68rem; letter-spacing:.06em;}
.auth-foot {font-size:.78rem; color:var(--text-muted); margin-top:14px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; border-top:1px solid var(--border); padding-top:12px;}
@media (max-width:900px) {.auth-panel {min-height:auto;}}
@media (max-width:640px) {
  [data-testid="stHorizontalBlock"]:has(.auth-panel) {flex-direction:column-reverse;}  /* sign-in form first on phones */
  .auth-hero h1 {font-size:1.6rem;}
}
"""

st.markdown(f"<style>{ROOT_CSS}{CSS}</style>", unsafe_allow_html=True)

SHIELD_SVG = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></svg>')
CHECK_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6EA8FF" stroke-width="2.4" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg>')
X_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" '
         'aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>')
OK_SVG = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" '
          'stroke-linejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5"/></svg>')

# ======================================================================
# 2. STATE, STORE, HELPERS
# ======================================================================
ss = st.session_state
_DEFAULTS = {
    "user": None, "data": None, "active_artifact_id": None, "uploader_nonce": 0, "case_nonce": 0,
    "auth_failures": 0, "auth_locked_until": 0.0, "api_key_override": "", "flash": None,
    "claimed_controls": list(auditor.CONTROL_IDS), "upload_error": None, "log_limit": 150,
}
for _k, _v in _DEFAULTS.items():
    if _k not in ss:
        ss[_k] = _v


@st.cache_resource(show_spinner=False)
def get_store():
    return create_store(config.FIRESTORE, config.LOCAL_DB_PATH, config.ALLOW_LOCAL_FALLBACK)


try:
    store = get_store()  # failures are not cached, so the next interaction retries
except Exception:
    log.exception("Storage backend unavailable")
    st.error("The account database is unreachable right now. Your data is safe; select Retry in a few seconds.", icon="🛑")
    st.button("Retry", type="primary")
    st.stop()


@st.cache_data(ttl=3600, show_spinner=False)
def discover_models(key_fingerprint: str, _api_key: str):
    return auditor.fetch_available_models(_api_key)


esc = html.escape
NAV = ["Workspace", "Audit history", "Activity log"]
LANG_BY_EXT = {"tf": "hcl", "tfvars": "hcl", "hcl": "hcl", "sql": "sql", "yaml": "yaml", "yml": "yaml", "json": "json", "md": "markdown", "txt": "text"}


def stretch(fn) -> dict:
    """Full-width kwarg that works across Streamlit versions."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if "width" in params:
        return {"width": "stretch"}
    if "use_container_width" in params:
        return {"use_container_width": True}
    return {}


def api_key() -> str:
    return (ss.get("api_key_override") or config.GEMINI_API_KEY or "").strip()


def _tz():
    try:
        name = st.context.timezone
        if name:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
    except Exception:
        pass
    return timezone.utc


def fmt_ts(iso: str, short: bool = False) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return iso
    tz = _tz()
    local = dt.astimezone(tz)
    suffix = " UTC" if tz is timezone.utc else ""
    return local.strftime("%H:%M" if short else "%b %d, %Y · %H:%M") + suffix


def fmt_bytes(n: int) -> str:
    n = int(n or 0)
    return f"{n} B" if n < 1024 else (f"{n / 1024:.1f} KB" if n < 1024 ** 2 else f"{n / 1024 ** 2:.2f} MB")


def lang_for(name: str) -> str:
    return LANG_BY_EXT.get((name or "").rsplit(".", 1)[-1].lower(), "text")


def chip(text, tone="neutral") -> str:
    return f'<span class="chip chip-{tone}">{esc(str(text))}</span>'


SEVERITY_TONE = {"CRITICAL": "crit", "HIGH": "fail", "MEDIUM": "warn", "LOW": "neutral"}


def card(name):
    return st.container(border=True, key=f"card_{name}")


def card_title(title, caption=""):
    cap = f'<div class="card-caption">{esc(caption)}</div>' if caption else ""
    st.markdown(f'<div class="card-title">{esc(title)}</div>{cap}', unsafe_allow_html=True)


def page_header(title, subtitle):
    st.markdown(f'<div class="page-header"><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>', unsafe_allow_html=True)


def empty_state(title, body):
    st.markdown(f'<div class="empty"><strong>{esc(title)}</strong>{esc(body)}</div>', unsafe_allow_html=True)


def demo_banner():
    if not config.DEMO_MODE:
        return
    degraded = bool(getattr(store, "degraded_reason", None))
    st.markdown(
        '<div class="demo-banner" role="status"><span class="demo-tag">DEMO</span>'
        "<span><b>Demo stage.</b> Secure Shift is running in a demo environment. Do not upload production secrets or real customer data.</span>"
        f'<span class="demo-meta"><span class="dot{" degraded" if degraded else ""}"></span>{esc(store.label)}</span></div>',
        unsafe_allow_html=True,
    )
    if degraded:
        st.warning(store.degraded_reason + " Running on the local demo store; history will not survive a restart.", icon="⚠️")


def stepper(steps):
    current = next((i for i, (_, done) in enumerate(steps) if not done), len(steps))
    items = ""
    for i, (label, done) in enumerate(steps):
        cls = "done" if done else ("current" if i == current else "todo")
        items += f'<div class="step {cls}"><span class="step-dot">{"✓" if done else i + 1}</span><span>{esc(label)}</span></div>'
    st.markdown(f'<div class="stepper">{items}</div>', unsafe_allow_html=True)


def render_finding(f, key_prefix, collapsible=True, expanded=None):
    ok = f.get("verdict") == "PASS"
    sev = f.get("severity", "HIGH")
    st.markdown(
        f'<div class="finding {"is-pass" if ok else "is-fail"}"><div class="finding-head">'
        f'<span class="mono">{esc(str(f.get("control_id", "UNKNOWN")))}</span>'
        f'<span class="finding-title">{esc(str(f.get("control_title", "")))}</span>'
        f'{chip(sev.title(), SEVERITY_TONE.get(sev, "neutral")) if not ok else ""}'
        f'{chip("Pass" if ok else "Fail", "pass" if ok else "fail")}</div>'
        f'<p>{esc(str(f.get("reason", "")))}</p></div>',
        unsafe_allow_html=True,
    )
    fix = f.get("remediation_fix")
    if not fix:
        return
    lang = f.get("remediation_language") or "text"
    if collapsible:
        with st.expander("Hardening tip" if ok else "Remediation patch", expanded=(not ok) if expanded is None else expanded):
            st.code(fix, language=lang)
    else:
        st.code(fix, language=lang)


# ======================================================================
# 3. DATA LAYER (session cache <-> persistent store)
# ======================================================================
def D(coll: str) -> list:
    return (ss.data or {}).get(coll, [])


def persist(coll: str, payload: dict) -> dict:
    rec = {**payload, "created_at": utcnow_iso()}
    try:
        rec["id"] = store.add(ss.user["uid"], coll, rec)
    except Exception:
        log.exception("Persist to %s failed", coll)
        rec["id"] = "unsaved_" + uuid.uuid4().hex[:12]
        rec["unsaved"] = True
        st.toast("Couldn't save to the database. This item is kept for this session only.", icon="⚠️")
    ss.data[coll].append(rec)
    return rec


def save_profile(**fields):
    try:
        store.update_profile(ss.user["uid"], fields)
    except Exception:
        log.exception("Profile update failed")


def active_artifact():
    aid = ss.active_artifact_id
    return next((a for a in D("artifacts") if a["id"] == aid), None) if aid else None


def current_audit():
    aid = ss.active_artifact_id
    runs = [a for a in D("audits") if a.get("artifact_id") == aid] if aid else []
    return runs[-1] if runs else None


def case_messages():
    aid = ss.active_artifact_id
    return [m for m in D("messages") if m.get("artifact_id") == aid] if aid else []


def set_active_artifact(aid):
    ss.active_artifact_id = aid
    ss.case_nonce += 1  # new widget key, so the case picker shows the new selection
    save_profile(active_artifact_id=aid)


def start_session(user, mode: str):
    ss.user = {"uid": user.uid, "email": user.email}
    ss.data = {c: [] for c in COLLECTIONS}
    profile = {}
    try:
        for c in COLLECTIONS:
            ss.data[c] = store.list(user.uid, c, config.HISTORY_LIMIT)
        profile = store.get_profile(user.uid)
    except Exception:
        log.exception("History load failed for %s", mask_email(user.email))
        ss.flash = ("Signed in, but your history couldn't be loaded. New activity will still be saved.", "⚠️")
    ids = {a["id"] for a in ss.data["artifacts"]}
    aid = profile.get("active_artifact_id")
    if aid not in ids:
        aid = ss.data["artifacts"][-1]["id"] if ss.data["artifacts"] else None
    ss.active_artifact_id = aid
    save_profile(email=user.email, last_login_at=utcnow_iso())
    persist("events", {"action": "signed_up" if mode == "signup" else "signed_in",
                       "summary": "Account created" if mode == "signup" else "Signed in", "backend": store.kind})
    na, nm, nf = len(ss.data["audits"]), len(ss.data["messages"]), len(ss.data["artifacts"])
    if not ss.flash:
        if mode == "signup":
            ss.flash = ("Account created. Your audits and conversations will be saved automatically.", "✅")
        elif na or nm or nf:
            ss.flash = (f"Welcome back. Restored {na} audits, {nm} messages and {nf} files.", "✅")
    log.info("Session started: user=%s mode=%s backend=%s audits=%d messages=%d files=%d",
             mask_email(user.email), mode, store.kind, na, nm, nf)


def sign_out():
    if ss.get("user"):
        persist("events", {"action": "signed_out", "summary": "Signed out"})
        log.info("Signed out: %s", mask_email(ss.user["email"]))
    for k in list(ss.keys()):
        del ss[k]


# ---------- workspace callbacks ----------
def new_case():
    set_active_artifact(None)
    ss.uploader_nonce += 1


def load_sample():
    rec = persist("artifacts", {
        "name": "ekyc_schema_vulnerable.sql", "content": SAMPLE_ARTIFACT, "size_bytes": len(SAMPLE_ARTIFACT.encode()),
        "sha256": hashlib.sha256(SAMPLE_ARTIFACT.encode()).hexdigest(), "source": "sample",
    })
    set_active_artifact(rec["id"])
    log.info("Sample artifact loaded: %s", rec["id"])


def on_upload():
    key = f"uploader_{ss.uploader_nonce}"
    up = ss.get(key)
    if up is None:
        return
    raw = up.getvalue()
    if len(raw) > config.MAX_ARTIFACT_BYTES:
        ss.upload_error = f"{up.name} is {fmt_bytes(len(raw))}. The limit is {fmt_bytes(config.MAX_ARTIFACT_BYTES)}."
        log.warning("Upload rejected (too large): %s %d bytes", up.name, len(raw))
        ss.uploader_nonce += 1
        return
    text = raw.decode("utf-8", errors="replace")
    rec = persist("artifacts", {
        "name": up.name, "content": text, "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(), "source": "upload",
    })
    ss.upload_error = None
    set_active_artifact(rec["id"])
    ss.uploader_nonce += 1  # clears the widget so the file isn't re-saved on rerun
    log.info("Artifact uploaded: name=%s size=%d id=%s", up.name, len(raw), rec["id"])


def on_case_change():
    val = ss.get(f"case_select_{ss.case_nonce}")
    if val and val != "__new__":
        ss.active_artifact_id = val
        save_profile(active_artifact_id=val)


def sync_controls():
    ss.claimed_controls = [c["id"] for c in auditor.CONTROLS if ss.get(f"ctl_{c['id']}", False)]


def open_case(aid):
    set_active_artifact(aid)
    ss.nav = NAV[0]


def queue_prompt(text):
    ss.pending_prompt = text


# ======================================================================
# 4. AUTHENTICATION
# ======================================================================
def handle_auth(mode: str, email: str, password: str):
    import time

    now = time.time()
    if ss.auth_locked_until > now:
        st.error(f"Too many failed attempts. Try again in {int(ss.auth_locked_until - now) + 1} seconds.")
        return
    try:
        with st.spinner("Creating your account..." if mode == "signup" else "Signing in..."):
            user = store.sign_up(email, password) if mode == "signup" else store.sign_in(email, password)
    except AuthError as exc:
        ss.auth_failures += 1
        if ss.auth_failures >= 5:
            ss.auth_locked_until = now + 60
            ss.auth_failures = 0
        log.info("Auth %s failed for %s: %s", mode, mask_email((email or "").strip().lower()), exc)
        st.error(str(exc))
        return
    except Exception:
        log.exception("Auth %s crashed", mode)
        st.error("Sign-in is temporarily unavailable. Try again shortly.")
        return
    ss.auth_failures = 0
    start_session(user, mode)
    st.rerun()


def render_auth():
    st.markdown(f"<style>{AUTH_CSS}</style>", unsafe_allow_html=True)
    demo_banner()
    left, right = st.columns([1.08, 1], gap="large", vertical_alignment="center")
    with left:
        st.markdown(
            f"""<div class="auth-panel">
<div class="brand"><div class="brand-mark">{SHIELD_SVG}</div>
<div><div class="brand-name">Secure Shift</div><div class="brand-sub">Autonomous GRC gateway</div></div></div>
<div class="auth-hero"><h1>Shift compliance left, before code ships.</h1>
<p>An adversarial AI lead auditor that cross-examines Terraform and SQL against SOC&nbsp;2, CCPA and GLBA controls, and keeps a complete evidence trail.</p></div>
<ul class="auth-points">
<li>{CHECK_SVG}<span>Zero-trust verification of every control your team claims</span></li>
<li>{CHECK_SVG}<span>Copy-paste remediation patches for each failed control</span></li>
<li>{CHECK_SVG}<span>Persistent audit ledger, conversations and submitted files</span></li>
</ul>
<div class="auth-badges"><span>SOC 2 TYPE II</span><span>CCPA § 1798</span><span>GLBA SAFEGUARDS</span><span>GEMINI 3.8</span></div>
</div>""",
            unsafe_allow_html=True,
        )
    with right:
        with st.container(border=True, key="card_auth"):
            st.markdown(
                f'<div class="auth-head">{chip("DEMO ENVIRONMENT", "warn")}<h2>Demo Login</h2>'
                "<p>Sign in to restore your audits, conversations and evidence.</p></div>",
                unsafe_allow_html=True,
            )
            tab_in, tab_up = st.tabs(["Sign in", "Create account"])
            with tab_in:
                with st.form("signin_form", border=False):
                    email = st.text_input("Email", placeholder="name@company.com", autocomplete="username")
                    pw = st.text_input("Password", type="password", autocomplete="current-password")
                    submitted = st.form_submit_button("Sign in", type="primary", **stretch(st.form_submit_button))
                if submitted:
                    handle_auth("signin", email, pw)
                if store.supports_password_reset:
                    with st.expander("Forgot your password?"):
                        with st.form("reset_form", border=False):
                            r_email = st.text_input("Account email", placeholder="name@company.com", key="reset_email")
                            if st.form_submit_button("Send reset link"):
                                try:
                                    store.send_password_reset(r_email)
                                    st.success("If that account exists, a reset link is on its way.")
                                except AuthError as exc:
                                    st.error(str(exc))
            with tab_up:
                with st.form("signup_form", border=False):
                    s_email = st.text_input("Email", placeholder="name@company.com", autocomplete="username", key="su_email")
                    s_pw = st.text_input("Password", type="password", autocomplete="new-password", key="su_pw",
                                         help="At least 8 characters.")
                    created = st.form_submit_button("Create account", type="primary", **stretch(st.form_submit_button))
                if created:
                    handle_auth("signup", s_email, s_pw)
            backend_note = ("Accounts and history are stored in Cloud Firestore." if store.kind == "firestore"
                            else "Accounts and history are stored in the local demo store.")
            st.markdown(f'<div class="auth-foot">{chip(store.label, "info")}<span>{esc(backend_note)}</span></div>',
                        unsafe_allow_html=True)


# ======================================================================
# 5. SIDEBAR
# ======================================================================
def render_sidebar():
    with st.sidebar:
        st.markdown(
            f'<div class="brand"><div class="brand-mark">{SHIELD_SVG}</div><div>'
            f'<div class="brand-name">Secure Shift{" <span class=pill-demo>DEMO</span>" if config.DEMO_MODE else ""}</div>'
            '<div class="brand-sub">Autonomous GRC gateway</div></div></div>',
            unsafe_allow_html=True,
        )
        email = ss.user["email"]
        st.markdown(
            f'<div class="user-card"><div class="avatar">{esc(email[:2].upper())}</div>'
            f'<div style="min-width:0"><div class="user-email" title="{esc(email)}">{esc(email)}</div>'
            f'<div class="user-sub">Signed in · {esc(store.label)}</div></div></div>',
            unsafe_allow_html=True,
        )
        page = st.radio("Navigation", NAV, key="nav", label_visibility="collapsed")

        st.markdown('<div class="side-label">AI model</div>', unsafe_allow_html=True)
        key = api_key()
        available = discover_models(hashlib.sha256(key.encode()).hexdigest()[:16], key) if key else None
        options = auditor.model_options(available)
        if ss.get("model_select") not in options:
            ss.pop("model_select", None)
        default = config.DEFAULT_MODEL if config.DEFAULT_MODEL in options else options[0]
        model = st.selectbox("Gemini model", options, index=options.index(default), format_func=auditor.model_label,
                             key="model_select", label_visibility="collapsed")
        info = auditor.CATALOG_BY_ID.get(model)
        st.caption(info.note if info else "Discovered from your API key.")
        failover = st.toggle("Auto-failover", value=True, key="failover",
                             help="If the selected model is out of quota or overloaded, the request is retried on the next available Gemini model.")

        st.markdown('<div class="side-label">API access</div>', unsafe_allow_html=True)
        if ss.get("api_key_override"):
            st.markdown(chip("Session key override", "info"), unsafe_allow_html=True)
        elif config.GEMINI_API_KEY:
            st.markdown(chip("Server key configured", "pass"), unsafe_allow_html=True)
        else:
            st.markdown(chip("API key required", "warn"), unsafe_allow_html=True)
        with st.expander("Use a different API key"):
            st.text_input("Gemini API key", type="password", key="api_key_override",
                          help="Used for this browser session only. Never saved.")
        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
        st.button("Sign out", key="signout_btn", on_click=sign_out, icon=":material/logout:", **stretch(st.button))
        st.markdown(
            '<div class="side-foot"><b>Target</b> IdentityAI (eKYC)<br>'
            "<b>Standards</b> SOC 2 Type II (CC6.1, CC6.3) · CCPA § 1798.100 · GLBA Safeguards Rule<br>"
            f"<b>Build</b> {esc(config.APP_VERSION)}</div>",
            unsafe_allow_html=True,
        )
    return page, model, failover


# ======================================================================
# 6. WORKSPACE
# ======================================================================
SAMPLE_ARTIFACT = """-- IdentityAI Microservice Schema: User eKYC Records
CREATE TABLE ekyc_id_verifications (
    verification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    -- VIOLATION: Storing plain text Social Security Numbers violates SOC2-CC6.1
    ssn_plaintext VARCHAR(11) NOT NULL,
    full_legal_name VARCHAR(255) NOT NULL,
    -- VIOLATION: Missing lifecycle TTL auto-purge triggers or partition for CCPA-1798
    biometric_face_scan_s3_uri VARCHAR(512) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- AWS Storage Definition for Biometric Selfies
-- VIOLATION: Using default aws/s3 key instead of dedicated CMEK (SOC2-CC6.3)
resource "aws_s3_bucket" "ekyc_selfies" {
  bucket = "identityai-user-selfies-raw"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "selfie_enc" {
  bucket = aws_s3_bucket.ekyc_selfies.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # Default AWS managed key, violates CMEK requirement
    }
  }
}
"""

SUGGESTIONS = [
    "Explain the most critical finding",
    "Write the Terraform patch for CMEK",
    "What evidence would make this pass?",
]


def report_markdown(audit: dict) -> str:
    r = audit["result"]
    out = [
        "# Secure Shift audit report", "",
        f"- **Artifact:** {audit.get('artifact_name', '')}",
        f"- **Verdict:** {r['audit_status']}",
        f"- **Confidence:** {r['confidence_score']}%",
        f"- **Model:** {audit.get('model_used', '')}",
        f"- **Run at (UTC):** {audit.get('created_at', '')}",
        f"- **Auditor account:** {ss.user['email']}", "",
        "## Executive summary", "", r["executive_summary"], "", "## Findings", "",
    ]
    for f in r["findings"]:
        out += [f"### {f['control_id']} - {f['control_title']}",
                f"**Verdict:** {f['verdict']}  |  **Severity:** {f['severity']}", "", f["reason"], "",
                f"```{f.get('remediation_language') or 'text'}", f["remediation_fix"], "```", ""]
    return "\n".join(out)


def render_verdict(audit):
    res = audit["result"]
    findings = res.get("findings", [])
    failed = res.get("failed_count", 0)
    approved = res.get("audit_status") == "APPROVED"
    severe = sum(1 for f in findings if f["verdict"] == "FAIL" and f["severity"] in ("CRITICAL", "HIGH"))
    model_used = audit.get("model_used", "")
    failover_note = ""
    if model_used and audit.get("model_requested") and model_used != audit["model_requested"]:
        failover_note = f" · failover from {esc(audit['model_requested'])}"
    st.markdown(
        f'<div class="verdict {"is-pass" if approved else "is-fail"}">'
        f'<div class="verdict-icon">{OK_SVG if approved else X_SVG}</div><div>'
        f'<div class="verdict-title">{"APPROVED" if approved else "REJECTED"}</div>'
        f'<div class="verdict-sub">{failed} of {len(findings)} claimed controls failed · {esc(model_used)}{failover_note} · {esc(fmt_ts(audit["created_at"]))}</div>'
        "</div></div>"
        '<div class="kpis">'
        f'<div class="kpi"><div class="kpi-label">Confidence</div><div class="kpi-value">{res.get("confidence_score", 0)}%</div></div>'
        f'<div class="kpi"><div class="kpi-label">Passed</div><div class="kpi-value">{len(findings) - failed} <small>of {len(findings)}</small></div></div>'
        f'<div class="kpi"><div class="kpi-label">Critical / high</div><div class="kpi-value">{severe}</div></div>'
        f'<div class="kpi"><div class="kpi-label">Response time</div><div class="kpi-value">{audit.get("latency_ms", 0) / 1000:.1f}<small> s</small></div></div>'
        "</div>"
        f'<div class="summary"><b>Executive summary</b><br>{esc(res.get("executive_summary", ""))}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("##### Control breakdown")
    first_fail = next((i for i, f in enumerate(findings) if f["verdict"] != "PASS"), -1)
    for i, f in enumerate(findings):
        render_finding(f, f"cur_{i}", expanded=(i == first_fail))  # open the top issue, keep the rest scannable
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Export report (Markdown)", report_markdown(audit), file_name="secure_shift_audit.md",
                           mime="text/markdown", key="dl_md_current", icon=":material/description:", **stretch(st.download_button))
    with c2:
        st.download_button("Export evidence (JSON)", json.dumps(audit, indent=2, default=str), file_name="secure_shift_audit.json",
                           mime="application/json", key="dl_json_current", icon=":material/data_object:", **stretch(st.download_button))


def run_audit_now(art, model, failover):
    claimed = list(ss.claimed_controls)
    try:
        with st.spinner(f"Lead Auditor is cross-examining {art['name']} with {auditor.model_label(model)}..."):
            out = auditor.run_audit(api_key(), model, art["name"], art["content"], claimed, failover)
    except auditor.AuditorError as exc:
        persist("events", {"action": "audit_failed", "summary": f"Audit failed on {art['name']}: {exc}",
                           "artifact_id": art["id"], "attempts": exc.attempts})
        st.error(str(exc), icon="🚫")
        if exc.attempts:
            with st.expander("Technical details"):
                st.json(exc.attempts)
        return
    rec = persist("audits", {
        "artifact_id": art["id"], "artifact_name": art["name"], "controls": claimed,
        "model_requested": model, "model_used": out["model_used"], "latency_ms": out["latency_ms"],
        "attempts": out["attempts"], "usage": out["usage"], "result": out["result"],
        "status": out["result"]["audit_status"], "failed_count": out["result"]["failed_count"],
    })
    if out["model_used"] != model:
        persist("events", {"action": "model_failover",
                           "summary": f"{model} unavailable; audit completed on {out['model_used']}", "artifact_id": art["id"]})
        ss.flash = (f"{auditor.model_label(model)} was unavailable, so the audit ran on {auditor.model_label(out['model_used'])}.", "🔁")
    log.info("Audit stored: id=%s status=%s model=%s", rec["id"], rec["status"], rec["model_used"])
    st.rerun()


def render_chat(art, audit, msgs, model, failover):
    with card("chat"):
        card_title("Cross-examination", "Challenge findings, submit revised code, or ask the Lead Auditor to clarify a remediation.")
        box = st.container(height=460, border=False, key="chatbox")
        with box:
            if not msgs:
                if art:
                    st.markdown('<div class="hint" style="margin:6px 0 10px">Start the conversation. Try one of these:</div>',
                                unsafe_allow_html=True)
                    with st.container(key="suggest"):
                        cols = st.columns(len(SUGGESTIONS))
                        for i, s in enumerate(SUGGESTIONS):
                            cols[i].button(s, key=f"sugg_{i}", on_click=queue_prompt, args=(s,))
                else:
                    empty_state("No artifact loaded", "Load an artifact to open a cross-examination thread.")
            for m in msgs:
                with st.chat_message("user" if m["role"] == "user" else "assistant"):
                    st.markdown(m["content"])
                    meta = fmt_ts(m["created_at"])
                    if m["role"] != "user" and m.get("model_used"):
                        meta += f" · {m['model_used']} · {m.get('latency_ms', 0) / 1000:.1f}s"
                    st.markdown(f'<div class="msg-meta">{esc(meta)}</div>', unsafe_allow_html=True)

        prompt = st.chat_input("Ask the Lead Auditor or paste updated code for review...", key="chat_input", disabled=not art)
        prompt = prompt or ss.pop("pending_prompt", None)
        if not (prompt and art):
            return
        history = list(msgs)
        with box:
            with st.chat_message("user"):
                st.markdown(prompt)
            persist("messages", {"artifact_id": art["id"], "audit_id": (audit or {}).get("id"), "role": "user", "content": prompt})
            with st.chat_message("assistant"):
                try:
                    with st.spinner("Lead Auditor is evaluating..."):
                        out = auditor.run_chat(api_key(), model, art, audit, history, prompt, failover, config.CHAT_CONTEXT_TURNS)
                except auditor.AuditorError as exc:
                    persist("events", {"action": "chat_failed", "summary": f"Lead Auditor reply failed: {exc}",
                                       "artifact_id": art["id"], "attempts": exc.attempts})
                    st.error(str(exc), icon="🚫")
                    return
                st.markdown(out["text"])
                persist("messages", {"artifact_id": art["id"], "audit_id": (audit or {}).get("id"), "role": "assistant",
                                     "content": out["text"], "model_used": out["model_used"], "latency_ms": out["latency_ms"]})
        st.rerun()


def render_workspace(model, failover):
    art, audit, msgs = active_artifact(), current_audit(), case_messages()
    head_l, head_r = st.columns([4, 1], vertical_alignment="bottom")
    with head_l:
        page_header("Shift-left regulatory gatekeeper",
                    "Cross-examine Terraform and SQL artifacts against SOC 2, CCPA and GLBA controls before they ship.")
    with head_r:
        st.button("New audit case", key="new_case_btn", on_click=new_case, icon=":material/add:", **stretch(st.button))

    claimed = ss.claimed_controls
    stepper([("Load artifact", bool(art)), ("Confirm controls", bool(art) and bool(claimed)), ("Review verdict", bool(audit))])
    # Inputs + conversation on the left, verdict on the right: findings and the chat stay side by side.
    col1, col2 = st.columns([1.05, 1.2], gap="large")

    with col1:
        with card("ingest"):
            card_title("Artifact", "Upload Terraform, SQL, YAML or policy text for IdentityAI.")
            arts = D("artifacts")
            if arts:
                lookup = {a["id"]: a for a in arts}
                opts = ([] if art else ["__new__"]) + [a["id"] for a in reversed(arts)]
                st.selectbox(
                    "Audit case", opts, index=opts.index(art["id"] if art else "__new__"), key=f"case_select_{ss.case_nonce}",
                    on_change=on_case_change,
                    format_func=lambda x: "New case (upload an artifact)" if x == "__new__"
                    else f'{lookup[x]["name"]} · {fmt_ts(lookup[x]["created_at"])}',
                    help="Every artifact keeps its own audits and conversation.",
                )
            st.file_uploader(
                "Upload code artifact", type=config.ALLOWED_EXTENSIONS, key=f"uploader_{ss.uploader_nonce}",
                on_change=on_upload, label_visibility="collapsed",
                help=f"Terraform, SQL, YAML, JSON or text. Max {fmt_bytes(config.MAX_ARTIFACT_BYTES)}.",
            )
            if ss.upload_error:
                st.error(ss.upload_error)
            if not art:
                st.button("Load sample artifact with known violations", key="sample_btn", on_click=load_sample,
                          icon=":material/science:")
            else:
                st.markdown(
                    f'<div class="meta-line">{chip("Loaded", "pass")}<span class="mono">{esc(art["name"])}</span>'
                    f'<span>{fmt_bytes(art.get("size_bytes", 0))}</span><span>·</span><span>{esc(fmt_ts(art["created_at"]))}</span></div>',
                    unsafe_allow_html=True,
                )
                with st.expander("Inspect artifact source", expanded=False):
                    st.code(art["content"], language=lang_for(art["name"]), line_numbers=True)

        with card("controls"):
            card_title("Claimed controls", "Select the controls your team says are implemented. The auditor verifies each one against the artifact.")
            for c in auditor.CONTROLS:
                st.checkbox(f"{c['id']} · {c['title']}", value=c["id"] in ss.claimed_controls, key=f"ctl_{c['id']}",
                            help=f"{c['framework']}: {c['tip']}", on_change=sync_controls)
            missing = []
            if not api_key():
                missing.append("an API key")
            if not art:
                missing.append("an artifact")
            if not ss.claimed_controls:
                missing.append("at least one control")
            run = st.button("Run audit", type="primary", key="run_audit_btn", disabled=bool(missing),
                            icon=":material/policy:", **stretch(st.button))
            if missing:
                st.markdown(f'<div class="hint">To run the audit, add {esc(", ".join(missing))}.</div>', unsafe_allow_html=True)
            if run and art:
                run_audit_now(art, model, failover)

        render_chat(art, audit, msgs, model, failover)

    with col2:
        with card("verdict"):
            card_title("Audit verdict")
            if not audit:
                empty_state("No audit has been run", "Load an artifact, confirm the claimed controls, then select Run audit.")
            else:
                render_verdict(audit)


# ======================================================================
# 7. AUDIT HISTORY
# ======================================================================
def render_history():
    page_header("Audit history", "Every audit run on your account, saved permanently and restored each time you sign in.")
    audits = list(reversed(D("audits")))
    if not audits:
        with card("empty_hist"):
            empty_state("No audits recorded yet", "Run an audit from the Workspace and it will appear here.")
        return

    approved = sum(1 for a in audits if a.get("status") == "APPROVED")
    st.markdown(
        '<div class="kpis">'
        f'<div class="kpi"><div class="kpi-label">Total audits</div><div class="kpi-value">{len(audits)}</div></div>'
        f'<div class="kpi"><div class="kpi-label">Approved</div><div class="kpi-value">{approved}</div></div>'
        f'<div class="kpi"><div class="kpi-label">Rejected</div><div class="kpi-value">{len(audits) - approved}</div></div>'
        f'<div class="kpi"><div class="kpi-label">Artifacts audited</div><div class="kpi-value">{len({a.get("artifact_id") for a in audits})}</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    f1, f2 = st.columns([1, 2], vertical_alignment="bottom")
    with f1:
        verdict_filter = st.radio("Verdict", ["All", "Rejected", "Approved"], horizontal=True, key="hist_filter")
    with f2:
        q = st.text_input("Search", placeholder="Filter by artifact or model", key="hist_q", label_visibility="collapsed")
    rows = [a for a in audits if verdict_filter == "All" or a.get("status") == verdict_filter.upper()]
    if q:
        ql = q.lower()
        rows = [a for a in rows if ql in a.get("artifact_name", "").lower() or ql in a.get("model_used", "").lower()]

    run_no = {a["id"]: len(audits) - i for i, a in enumerate(audits)}
    with card("ledger"):
        card_title("Runs", f"{len(rows)} of {len(audits)} shown, newest first.")
        body = ""
        for a in rows:
            ok = a.get("status") == "APPROVED"
            body += (f"<tr><td>#{run_no[a['id']]}</td><td>{esc(fmt_ts(a['created_at']))}</td><td class='mono'>{esc(a.get('artifact_name', ''))}</td>"
                     f"<td>{esc(a.get('model_used', ''))}</td><td>{chip('Approved' if ok else 'Rejected', 'pass' if ok else 'fail')}</td>"
                     f"<td>{a.get('failed_count', 0)}</td><td>{(a.get('result') or {}).get('confidence_score', '')}%</td></tr>")
        st.markdown(
            '<div class="table-wrap"><table class="ledger"><thead><tr><th>Run</th><th>Time</th><th>Artifact</th><th>Model</th>'
            f"<th>Verdict</th><th>Failed</th><th>Confidence</th></tr></thead><tbody>{body}</tbody></table></div>",
            unsafe_allow_html=True,
        )

    for a in rows:
        n = run_no[a["id"]]
        res = a.get("result") or {}
        ok = a.get("status") == "APPROVED"
        with st.expander(f"Run #{n} · {a.get('artifact_name', '')} · {'Approved' if ok else 'Rejected'} · {fmt_ts(a['created_at'])}"):
            st.markdown(
                f'<div class="meta-line">{chip("Approved" if ok else "Rejected", "pass" if ok else "fail")}'
                f'<span class="mono">{esc(a.get("model_used", ""))}</span><span>· {a.get("latency_ms", 0) / 1000:.1f}s</span>'
                f'<span>· controls: {esc(", ".join(a.get("controls", [])))}</span></div>'
                f'<div class="summary"><b>Executive summary</b><br>{esc(res.get("executive_summary", ""))}</div>',
                unsafe_allow_html=True,
            )
            for i, f in enumerate(res.get("findings", [])):
                render_finding(f, f"h{a['id']}_{i}", collapsible=False)
            b1, b2, b3 = st.columns(3)
            b1.button("Open in workspace", key=f"open_{a['id']}", on_click=open_case, args=(a.get("artifact_id"),),
                      icon=":material/open_in_new:", **stretch(st.button))
            b2.download_button("Report (Markdown)", report_markdown(a), file_name=f"secure_shift_run_{n}.md",
                               mime="text/markdown", key=f"dlmd_{a['id']}", **stretch(st.download_button))
            b3.download_button("Evidence (JSON)", json.dumps(a, indent=2, default=str), file_name=f"secure_shift_run_{n}.json",
                               mime="application/json", key=f"dljs_{a['id']}", **stretch(st.download_button))


# ======================================================================
# 8. ACTIVITY LOG
# ======================================================================
EVENT_LABELS = {
    "signed_in": ("Account", "info"), "signed_up": ("Account", "info"), "signed_out": ("Account", "neutral"),
    "model_failover": ("System", "warn"), "audit_failed": ("Error", "fail"), "chat_failed": ("Error", "fail"),
}
TYPE_FILTERS = {"Files": {"file"}, "Audits": {"audit"}, "Chat": {"user", "assistant"}, "Account & system": {"event"}}


def activity_entries():
    names = {a["id"]: a.get("name", "") for a in D("artifacts")}
    entries = [{"kind": "file", "rec": a, "case": a["id"]} for a in D("artifacts")]
    entries += [{"kind": "audit", "rec": a, "case": a.get("artifact_id")} for a in D("audits")]
    entries += [{"kind": "user" if m.get("role") == "user" else "assistant", "rec": m, "case": m.get("artifact_id")} for m in D("messages")]
    entries += [{"kind": "event", "rec": e, "case": e.get("artifact_id")} for e in D("events")]
    for e in entries:
        e["ts"] = e["rec"].get("created_at", "")
        e["case_name"] = names.get(e["case"], "")
    return entries


def entry_text(e) -> str:
    r = e["rec"]
    return " ".join(str(r.get(k, "")) for k in ("name", "content", "summary", "artifact_name", "model_used", "status")).lower() + " " + e["case_name"].lower()


def log_head(ts, chip_html, title, meta=""):
    st.markdown(
        f'<div class="log-head"><span class="log-time">{esc(fmt_ts(ts))}</span>{chip_html}'
        f'<span class="log-title">{esc(title)}</span><span class="log-meta">{esc(meta)}</span></div>',
        unsafe_allow_html=True,
    )


def render_entry(e):
    r, k = e["rec"], e["kind"]
    with st.container(key=f"entry_{k}_{r['id']}"):
        if k == "file":
            log_head(e["ts"], chip("File", "violet"), f"Submitted {r.get('name', '')}",
                     f"{fmt_bytes(r.get('size_bytes', 0))} · sha256 {str(r.get('sha256', ''))[:12]} · {r.get('source', 'upload')}")
            with st.expander("View file"):
                st.code(r.get("content", ""), language=lang_for(r.get("name", "")), line_numbers=True)
                st.download_button("Download file", r.get("content", ""), file_name=r.get("name", "artifact.txt"),
                                   key=f"dlf_{r['id']}", icon=":material/download:")
        elif k == "audit":
            res = r.get("result") or {}
            ok = r.get("status") == "APPROVED"
            log_head(e["ts"], chip("Approved" if ok else "Rejected", "pass" if ok else "fail"), f"Audit · {r.get('artifact_name', '')}",
                     f"{r.get('model_used', '')} · {r.get('latency_ms', 0) / 1000:.1f}s · {r.get('failed_count', 0)} failed · confidence {res.get('confidence_score', '')}%")
            st.markdown(f'<div class="summary">{esc(res.get("executive_summary", ""))}</div>', unsafe_allow_html=True)
            with st.expander(f"Findings ({len(res.get('findings', []))})"):
                for i, f in enumerate(res.get("findings", [])):
                    render_finding(f, f"lg{r['id']}_{i}", collapsible=False)
        elif k == "user":
            log_head(e["ts"], chip("Developer", "info"), "You", e["case_name"])
            st.markdown(r.get("content", ""))
        elif k == "assistant":
            log_head(e["ts"], chip("Lead Auditor", "pass"), "Lead Auditor",
                     f"{r.get('model_used', '')} · {r.get('latency_ms', 0) / 1000:.1f}s · {e['case_name']}")
            st.markdown(r.get("content", ""))
        else:
            label, tone = EVENT_LABELS.get(r.get("action"), ("System", "neutral"))
            log_head(e["ts"], chip(label, tone), r.get("summary", r.get("action", "")), e["case_name"])


def transcript_markdown(entries) -> str:
    out = [f"# Secure Shift activity log - {ss.user['email']}", ""]
    for e in entries:
        r = e["rec"]
        ts = r.get("created_at", "")
        if e["kind"] == "file":
            out += [f"## {ts} - File submitted: {r.get('name', '')}", f"```{lang_for(r.get('name', ''))}", r.get("content", ""), "```", ""]
        elif e["kind"] == "audit":
            res = r.get("result") or {}
            out += [f"## {ts} - Audit {r.get('status', '')}: {r.get('artifact_name', '')} ({r.get('model_used', '')})",
                    res.get("executive_summary", ""), ""]
        elif e["kind"] in ("user", "assistant"):
            who = "Developer" if e["kind"] == "user" else f"Lead Auditor ({r.get('model_used', '')})"
            out += [f"## {ts} - {who}", r.get("content", ""), ""]
        else:
            out += [f"- {ts} - {r.get('summary', r.get('action', ''))}", ""]
    return "\n".join(out)


def render_activity():
    page_header("Activity log", "A complete trail of sign-ins, submitted files, audit verdicts and Lead Auditor conversations.")
    entries = activity_entries()
    if not entries:
        with card("empty_log"):
            empty_state("No activity yet", "Your sign-ins, files, audits and chats will be recorded here.")
        return

    c1, c2, c3 = st.columns([2.2, 1.6, 1.2])
    with c1:
        q = st.text_input("Search the log", placeholder="Search files, chat, verdicts...", key="log_q", label_visibility="collapsed")
    with c2:
        case_ids = ["__all__"] + [a["id"] for a in reversed(D("artifacts"))]
        names = {a["id"]: a.get("name", "") for a in D("artifacts")}
        case = st.selectbox("Case", case_ids, key="log_case", label_visibility="collapsed",
                            format_func=lambda x: "All cases" if x == "__all__" else f"{names.get(x, x)}")
    with c3:
        order = st.selectbox("Order", ["Newest first", "Oldest first"], key="log_order", label_visibility="collapsed")
    if hasattr(st, "pills"):
        types_sel = st.pills("Show", list(TYPE_FILTERS), selection_mode="multi", default=list(TYPE_FILTERS), key="log_types",
                             label_visibility="collapsed")
    else:
        types_sel = st.multiselect("Show", list(TYPE_FILTERS), default=list(TYPE_FILTERS), key="log_types")
    kinds = set().union(*(TYPE_FILTERS[t] for t in (types_sel or [])))

    rows = [e for e in entries if e["kind"] in kinds and (case == "__all__" or e["case"] == case)]
    if q:
        ql = q.lower()
        rows = [e for e in rows if ql in entry_text(e)]
    rows.sort(key=lambda e: e["ts"], reverse=(order == "Newest first"))

    counts = {k: sum(1 for e in rows if e["kind"] in v) for k, v in TYPE_FILTERS.items()}
    st.markdown(
        f'<div class="log-stats"><span><b>{len(rows)}</b> entries</span>'
        + "".join(f"<span><b>{v}</b> {esc(k.lower())}</span>" for k, v in counts.items())
        + "</div>",
        unsafe_allow_html=True,
    )

    shown = rows[: ss.log_limit]
    with st.container(height=640, border=True, key="logwindow"):
        if not shown:
            empty_state("Nothing matches these filters", "Clear the search or select more entry types.")
        for e in shown:
            render_entry(e)
        if len(rows) > len(shown):
            if st.button(f"Show {min(150, len(rows) - len(shown))} more", key="log_more"):
                ss.log_limit += 150
                st.rerun()

    d1, d2, _ = st.columns([1, 1, 2])
    d1.download_button("Download transcript (.md)", transcript_markdown(sorted(rows, key=lambda e: e["ts"])),
                       file_name="secure_shift_activity.md", mime="text/markdown", key="dl_log_md", **stretch(st.download_button))
    d2.download_button("Download log (.json)", json.dumps([{"type": e["kind"], **e["rec"]} for e in rows], indent=2, default=str),
                       file_name="secure_shift_activity.json", mime="application/json", key="dl_log_json", **stretch(st.download_button))


# ======================================================================
# 9. ROUTER
# ======================================================================
if not ss.user:
    render_auth()
    st.stop()

page, model, failover = render_sidebar()
demo_banner()
if ss.flash:
    msg, icon = ss.flash
    st.toast(msg, icon=icon)
    ss.flash = None

if page == NAV[0]:
    render_workspace(model, failover)
elif page == NAV[1]:
    render_history()
else:
    render_activity()
