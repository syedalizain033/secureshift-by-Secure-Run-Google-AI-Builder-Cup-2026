"""
Secure Shift - Autonomous AI-Driven Lead Auditor & Shift-Left GRC Gateway
Reference Target: IdentityAI (eKYC Platform)
Regulatory Standards: SOC 2 Type II, CCPA, GLBA
UI: enterprise design system (light canvas, navy chrome, IBM Plex). Requires Streamlit >= 1.39.
"""

import os
import json
import html
from datetime import datetime
import streamlit as st
from google import genai
from google.genai import types
from google.genai.errors import APIError

# ==========================================
# 1. PAGE CONFIGURATION & DESIGN TOKENS
# ==========================================
st.set_page_config(
    page_title="Secure Shift | GRC Gateway",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Single source of truth for the visual language (emitted as CSS variables).
TOKENS = {
    "navy-900": "#0B2545", "navy-800": "#13315C", "navy-700": "#1F4177",
    "blue-600": "#1D5FD1", "blue-700": "#1649A6",
    "bg": "#F4F6F9", "surface": "#FFFFFF", "border": "#D8DEE8", "border-strong": "#B8C2D1",
    "text": "#16202E", "text-muted": "#556377",
    "pass": "#17744A", "pass-bg": "#E6F4EC",
    "fail": "#B42318", "fail-bg": "#FDECEA",
    "warn": "#8A5200", "warn-bg": "#FFF4DB",
}
ROOT_CSS = ":root{" + "".join(f"--{k}:{v};" for k, v in TOKENS.items()) + "}"

CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');
html, body, .stApp, .stApp button, .stApp input, .stApp textarea, .stMarkdown {font-family:'IBM Plex Sans',-apple-system,'Segoe UI',sans-serif;}
code, pre, kbd, .mono {font-family:'IBM Plex Mono',ui-monospace,monospace !important;}
.stApp {background:var(--bg); color:var(--text);}
header[data-testid="stHeader"] {background:transparent;}
footer, #MainMenu {visibility:hidden;}
.block-container {padding-top:2rem; max-width:1320px;}
h1,h2,h3,h4 {color:var(--navy-900); letter-spacing:-0.01em; font-weight:600;}
.stApp :focus-visible {outline:2px solid var(--blue-600); outline-offset:2px;}

/* Sidebar chrome */
section[data-testid="stSidebar"] {background:var(--navy-900); border-right:1px solid var(--navy-700);}
section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] * {color:#DCE5F2;}
section[data-testid="stSidebar"] [data-baseweb="input"], section[data-testid="stSidebar"] [data-baseweb="input"] > div,
section[data-testid="stSidebar"] [data-baseweb="select"] > div {background:var(--navy-800) !important; border-color:var(--navy-700) !important;}
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] [data-baseweb="select"] * {color:#fff !important; -webkit-text-fill-color:#fff;}
section[data-testid="stSidebar"] [data-baseweb="select"] svg {fill:#fff;}
section[data-testid="stSidebar"] [role="radiogroup"] {gap:2px;}
section[data-testid="stSidebar"] [role="radiogroup"] label {width:100%; padding:9px 12px; border-radius:6px; border-left:3px solid transparent; cursor:pointer;}
section[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {position:absolute; opacity:0; width:0; height:0; overflow:hidden;}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {background:var(--navy-800);}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background:var(--navy-800); border-left-color:#6EA8FF;}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {color:#fff; font-weight:600;}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:focus-visible) {outline:2px solid #6EA8FF;}
.brand {display:flex; align-items:center; gap:10px; padding:4px 0 20px;}
.brand-mark {width:36px; height:36px; border-radius:8px; background:var(--blue-600); display:flex; align-items:center; justify-content:center;}
.brand-name {font-weight:600; font-size:1.05rem; color:#fff; line-height:1.2;}
.brand-sub {font-size:.75rem; color:#9FB3D1;}
.side-label {font-size:.75rem; font-weight:600; color:#9FB3D1; margin:22px 0 6px;}
.side-foot {font-size:.78rem; color:#9FB3D1; line-height:1.7; border-top:1px solid var(--navy-700); margin-top:24px; padding-top:14px;}

/* Page + cards */
.page-header h1 {font-size:1.6rem; margin:0;}
.page-header p {color:var(--text-muted); margin:4px 0 18px; max-width:70ch;}
[class*="st-key-card_"] {background:var(--surface); border:1px solid var(--border) !important; border-radius:8px; padding:20px 22px !important; box-shadow:0 1px 2px rgba(16,24,40,.06);}
.card-title {font-size:1rem; font-weight:600; color:var(--navy-900);}
.card-caption {font-size:.85rem; color:var(--text-muted); margin:2px 0 14px;}
.hint {font-size:.82rem; color:var(--text-muted);}

/* Stepper */
.stepper {display:flex; gap:8px; flex-wrap:wrap; margin:0 0 20px;}
.step {display:flex; align-items:center; gap:8px; flex:1; min-width:170px; padding:10px 14px; background:var(--surface); border:1px solid var(--border); border-radius:6px; font-size:.875rem; color:var(--text-muted);}
.step-dot {width:22px; height:22px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center; font-size:.75rem; font-weight:600; background:#E7ECF3; color:var(--text-muted);}
.step.current {border-color:var(--blue-600); color:var(--navy-900); font-weight:500;}
.step.current .step-dot {background:var(--blue-600); color:#fff;}
.step.done {color:var(--text);}
.step.done .step-dot {background:var(--pass); color:#fff;}

/* Status chips */
.chip {display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:4px; font-size:.78rem; font-weight:600; border:1px solid transparent; white-space:nowrap;}
.chip::before {content:""; width:6px; height:6px; border-radius:50%; background:currentColor;}
.stApp .chip-pass {color:var(--pass); background:var(--pass-bg); border-color:#BFE3CE;}
.stApp .chip-fail {color:var(--fail); background:var(--fail-bg); border-color:#F4C7C2;}
.stApp .chip-warn {color:var(--warn); background:var(--warn-bg); border-color:#F2D9A4;}
.stApp .chip-neutral {color:var(--text-muted); background:#EEF1F6; border-color:var(--border);}

/* Results */
.kpis {display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px;}
.kpi {border:1px solid var(--border); border-radius:6px; padding:12px 14px; background:#fff;}
.kpi-label {font-size:.78rem; color:var(--text-muted); margin-bottom:6px;}
.kpi-value {font-size:1.3rem; font-weight:600; color:var(--navy-900); line-height:1.3;}
.summary {background:#F8FAFC; border:1px solid var(--border); border-radius:6px; padding:12px 14px; font-size:.9rem; line-height:1.55; margin-bottom:8px;}
.finding {border:1px solid var(--border); border-left:4px solid var(--border-strong); border-radius:6px; padding:12px 14px; margin:10px 0 6px; background:#fff;}
.finding.is-pass {border-left-color:var(--pass);}
.finding.is-fail {border-left-color:var(--fail);}
.finding-head {display:flex; align-items:center; gap:10px; flex-wrap:wrap;}
.finding-title {font-weight:600; color:var(--navy-900); flex:1;}
.finding p {margin:8px 0 0; font-size:.9rem; line-height:1.55;}
.mono {font-size:.8rem; color:var(--text-muted);}
.empty {text-align:center; padding:36px 16px; color:var(--text-muted);}
.empty strong {display:block; color:var(--navy-900); font-size:1rem; margin-bottom:4px;}

/* Widgets */
.stButton > button, .stDownloadButton > button {border-radius:6px; font-weight:500; border:1px solid var(--border-strong); background:#fff; color:var(--navy-900); transition:background .15s, border-color .15s;}
.stButton > button:hover, .stDownloadButton > button:hover {border-color:var(--blue-600); color:var(--blue-700); background:#F3F7FF;}
.stButton > button[kind="primary"], button[data-testid="stBaseButton-primary"] {background:var(--blue-600); border-color:var(--blue-600); color:#fff; font-weight:600; padding:.55rem 1.2rem;}
.stButton > button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover {background:var(--blue-700); border-color:var(--blue-700); color:#fff;}
.stButton > button:disabled {background:#EEF1F6; border-color:var(--border); color:#8A96A8;}
[data-testid="stFileUploaderDropzone"] {background:#F8FAFC; border:1px dashed var(--border-strong); border-radius:6px;}
[data-testid="stExpander"] {border:1px solid var(--border); border-radius:6px; background:#fff;}
@media (max-width:900px) {.kpis {grid-template-columns:repeat(2,1fr);}}
@media (prefers-reduced-motion:reduce) {* {transition:none !important;}}
"""
st.markdown(f"<style>{ROOT_CSS}{CSS}</style>", unsafe_allow_html=True)

# ==========================================
# 2. SESSION STATE INITIALIZATION
# ==========================================
if "api_key" not in st.session_state:
    st.session_state.api_key = os.environ.get("GEMINI_API_KEY", "")
if "uploaded_artifact" not in st.session_state:
    st.session_state.uploaded_artifact = None
if "uploaded_artifact_name" not in st.session_state:
    st.session_state.uploaded_artifact_name = ""
if "current_audit_result" not in st.session_state:
    st.session_state.current_audit_result = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "audit_history" not in st.session_state:
    st.session_state.audit_history = []

# ==========================================
# 3. LEAD AUDITOR SYSTEM PROMPTS & SCHEMAS
# ==========================================
LEAD_AUDITOR_SYSTEM_PROMPT = """
You are the Autonomous Principal GRC Auditor for "Secure Shift", an adversarial regulatory compliance evaluation gateway.
You are actively cross-examining architecture and code artifacts submitted for "IdentityAI" (an enterprise eKYC identity verification microservice).

Applicable Standards:
1. [SOC2-CC6.1] PII/SSN Field-Level AES-256 Encryption at Rest. (Look for hardcoded plaintexts, missing pgcrypto/pgp_sym_encrypt, or lack of field-level encryption).
2. [CCPA-1798] 24-Hour Temp Image Auto-Deletion Policy for facial biometrics/government IDs. (Look for explicit TTL policies, lifecycle expiration rules, or cron teardown).
3. [SOC2-CC6.3] Customer-Managed Encryption Keys (CMEK) via AWS KMS or HashiCorp Vault. (Verify that default cloud provider keys are not used when CMEK is declared).

Audit Protocol:
- Practice Strict Zero-Trust Verification: Developers claim their checklist is implemented. Do NOT trust their checklist claims unless verified in the uploaded code artifact.
- Flag discrepancies between claimed checklist items and actual artifact implementation as an automatic FAILURE.
- If the artifact lacks mandatory controls, verdict for that control is "FAIL".
- If any checked or mandatory control fails, the overall audit status is REJECTED. Only return APPROVED if all active controls are strictly validated.

You must respond ONLY with a valid JSON object strictly matching this schema:
{
  "audit_status": "APPROVED" | "REJECTED",
  "confidence_score": 98,
  "executive_summary": "Concise high-level summary of the architectural posture and key compliance risks.",
  "findings": [
    {
      "control_id": "[SOC2-CC6.1]" | "[CCPA-1798]" | "[SOC2-CC6.3]",
      "control_title": "Control Title Here",
      "verdict": "PASS" | "FAIL",
      "reason": "Technical observation of code discrepancy or compliant implementation.",
      "remediation_fix": "Concrete code snippet or Terraform/SQL patch to resolve the violation."
    }
  ]
}
"""

CHAT_AUDITOR_SYSTEM_PROMPT = """
You are the Lead Auditor of Secure Shift. You are interacting with the lead developer of IdentityAI.
You maintain a formal, zero-trust, highly technical auditor tone.
You have access to the initial audit findings, the submitted code, and the regulatory standards (SOC 2, CCPA, GLBA).
Provide precise remediation guidance, point out vulnerabilities, and verify code patches submitted in the chat.
"""

# ==========================================
# 4. HELPER FUNCTIONS & GEMINI CLIENT
# ==========================================
def get_gemini_client():
    """Initializes and returns the Google GenAI Client with error safety."""
    if not st.session_state.api_key:
        st.error("⚠️ Google AI Studio API Key is missing. Please configure it in the sidebar.")
        return None
    try:
        return genai.Client(api_key=st.session_state.api_key)
    except Exception as e:
        st.error(f"Failed to initialize Google GenAI Client: {str(e)}")
        return None

def get_available_models():
    """Returns guaranteed stable production models compatible with the SDK."""
    return ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-3.8-flash"]

def execute_audit(artifact_code: str, file_name: str, active_controls: list, selected_model: str):
    client = get_gemini_client()
    if not client:
        return None

    audit_payload = {
        "target_application": "IdentityAI (eKYC Platform)",
        "file_analyzed": file_name,
        "developer_claimed_controls": active_controls,
        "submitted_artifact_code": artifact_code
    }

    user_prompt = f"Please perform an audit examination on the following payload:\n```json\n{json.dumps(audit_payload, indent=2)}\n```"

    try:
        # Use clean model name without 'models/' prefix for correct SDK routing
        model_name = selected_model.replace("models/", "")
        
        response = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=LEAD_AUDITOR_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        parsed_json = json.loads(response.text)
        return parsed_json
    except APIError as e:
        st.error(f"Gemini API Error ({e.code}): {e.message}")
        return None
    except Exception as e:
        st.error(f"Audit execution error: {str(e)}")
        return None

def execute_chat_followup(user_message: str, selected_model: str):
    """Handles multi-turn conversational cross-examination with context using the selected model."""
    client = get_gemini_client()
    if not client:
        return None

    context_primer = f"""
Audit Context:
- Target: IdentityAI
- File: {st.session_state.uploaded_artifact_name}
- Initial Audit Verdict: {st.session_state.current_audit_result.get('audit_status', 'N/A') if st.session_state.current_audit_result else 'No prior audit run'}
- Executive Summary: {st.session_state.current_audit_result.get('executive_summary', 'N/A') if st.session_state.current_audit_result else 'N/A'}

Original Code Artifact:
{st.session_state.uploaded_artifact}
"""
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=f"AUDIT CONTEXT:\n{context_primer}")]),
        types.Content(role="model", parts=[types.Part.from_text(text="Understood. Lead Auditor ready to cross-examine technical artifacts and remediations.")])
    ]

    for msg in st.session_state.chat_history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))

    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

    try:
        model_name = selected_model.replace("models/", "")
        
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=CHAT_AUDITOR_SYSTEM_PROMPT,
                temperature=0.3
            )
        )
        return response.text
    except APIError as e:
        st.error(f"Chat API Error ({e.code}): {e.message}. Please verify your API key and model selection.")
        return None
    except Exception as e:
        st.error(f"Chat error: {str(e)}")
        return None

sample_artifact = """-- IdentityAI Microservice Schema: User eKYC Records
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

# ==========================================
# 5. DESIGN-SYSTEM COMPONENTS
# ==========================================
esc = html.escape
NAV = ["Active audit", "Audit history"]
CONTROLS = [
    ("[SOC2-CC6.1]", "PII/SSN field-level AES-256 encryption", "Mandates that sensitive PII such as SSN must be encrypted before hitting persistence."),
    ("[CCPA-1798]", "24-hour temp image auto-deletion", "Enforces that biometric snapshots/gov IDs expire within 24 hours of KYC resolution."),
    ("[SOC2-CC6.3]", "Customer-managed encryption keys (CMEK)", "Requires customer-managed KMS key ARNs instead of standard AWS/GCP default keys."),
]

def chip(text, tone="neutral"):
    return f'<span class="chip chip-{tone}">{esc(str(text))}</span>'

def card(name):
    return st.container(border=True, key=f"card_{name}")

def card_title(title, caption=""):
    cap = f'<div class="card-caption">{esc(caption)}</div>' if caption else ""
    st.markdown(f'<div class="card-title">{esc(title)}</div>{cap}', unsafe_allow_html=True)

def page_header(title, subtitle):
    st.markdown(f'<div class="page-header"><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>', unsafe_allow_html=True)

def stepper(steps):
    current = next((i for i, (_, done) in enumerate(steps) if not done), len(steps))
    items = ""
    for i, (label, done) in enumerate(steps):
        cls = "done" if done else ("current" if i == current else "todo")
        items += f'<div class="step {cls}"><span class="step-dot">{"✓" if done else i + 1}</span><span>{esc(label)}</span></div>'
    st.markdown(f'<div class="stepper">{items}</div>', unsafe_allow_html=True)

def render_finding(f, collapsible=True):
    ok = f.get("verdict", "FAIL") == "PASS"
    st.markdown(
        f'<div class="finding {"is-pass" if ok else "is-fail"}"><div class="finding-head">'
        f'<span class="mono">{esc(str(f.get("control_id", "UNKNOWN")))}</span>'
        f'<span class="finding-title">{esc(str(f.get("control_title", "")))}</span>'
        f'{chip("Pass" if ok else "Fail", "pass" if ok else "fail")}</div>'
        f'<p>{esc(str(f.get("reason", "")))}</p></div>', unsafe_allow_html=True)
    fix = f.get("remediation_fix")
    if fix and collapsible:
        with st.expander("Remediation patch", expanded=not ok):
            st.code(fix, language="sql")
    elif fix:
        st.code(fix, language="sql")

def count_failed(res):
    return sum(1 for f in res.get("findings", []) if f.get("verdict") != "PASS")

# ==========================================
# 6. SIDEBAR NAVIGATION & SETTINGS
# ==========================================
with st.sidebar:
    st.markdown("""
<div class="brand">
<div class="brand-mark"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/></svg></div>
<div><div class="brand-name">Secure Shift</div><div class="brand-sub">Autonomous GRC gateway</div></div>
</div>
""", unsafe_allow_html=True)

    app_mode = st.radio("Navigation", NAV, label_visibility="collapsed")

    st.markdown('<div class="side-label">Configuration</div>', unsafe_allow_html=True)
    api_key_input = st.text_input(
        "Google AI Studio API key",
        value=st.session_state.api_key,
        type="password",
        help="Input your Gemini API key from Google AI Studio."
    )
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input
    st.markdown(chip("Key configured", "pass") if st.session_state.api_key else chip("Key required", "warn"), unsafe_allow_html=True)

    dynamic_models = get_available_models()
    default_index = dynamic_models.index("gemini-1.5-flash") if "gemini-1.5-flash" in dynamic_models else 0
    selected_model = st.selectbox("Gemini model", options=dynamic_models, index=default_index, help="Stable models verified for your API key.")

    st.markdown("""
<div class="side-foot">
<b>Target:</b> IdentityAI (eKYC)<br>
<b>Standards</b><br>SOC 2 Type II (CC6.1, CC6.3)<br>CCPA § 1798.100<br>GLBA Safeguards Rule
</div>
""", unsafe_allow_html=True)

# ==========================================
# 7. PAGE 1: ACTIVE AUDIT
# ==========================================
if app_mode == NAV[0]:
    page_header("Shift-left regulatory gatekeeper", "Cross-examine Terraform and SQL artifacts against SOC 2, CCPA and GLBA controls before they ship.")

    claimed = [c for i, (c, _, _) in enumerate(CONTROLS) if st.session_state.get(f"chk_{i}", True)]
    has_artifact = bool(st.session_state.uploaded_artifact)
    stepper([("Load artifact", has_artifact), ("Confirm controls", has_artifact and bool(claimed)), ("Review verdict", bool(st.session_state.current_audit_result))])

    col1, col2 = st.columns([1, 1.2], gap="large")

    # --- LEFT: INPUTS & CONTROLS ---
    with col1:
        with card("ingest"):
            card_title("Artifact", "Upload Terraform, SQL or policy text for IdentityAI.")
            uploaded_file = st.file_uploader(
                "Upload code artifact (.tf, .sql, .txt)", type=["tf", "sql", "txt"],
                label_visibility="collapsed",
                help="Upload Terraform architecture, DB schema definitions, or policy files for IdentityAI."
            )
            if uploaded_file is not None:
                st.session_state.uploaded_artifact = uploaded_file.getvalue().decode("utf-8", errors="replace")
                st.session_state.uploaded_artifact_name = uploaded_file.name

            if not st.session_state.uploaded_artifact:
                if st.button("Load sample artifact with known violations"):
                    st.session_state.uploaded_artifact = sample_artifact
                    st.session_state.uploaded_artifact_name = "ekyc_schema_vulnerable.sql"
                    st.rerun()
            else:
                st.markdown(chip("Loaded", "pass") + f' <span class="mono">{esc(st.session_state.uploaded_artifact_name)}</span>', unsafe_allow_html=True)
                with st.expander("Inspect artifact source", expanded=False):
                    st.code(st.session_state.uploaded_artifact, language="sql")

        with card("controls"):
            card_title("Claimed controls", "Select the controls your team says are implemented. The auditor verifies each one against the artifact.")
            for i, (cid, title, tip) in enumerate(CONTROLS):
                st.checkbox(f"{cid} {title}", value=True, key=f"chk_{i}", help=tip)
            active_controls = [c for i, (c, _, _) in enumerate(CONTROLS) if st.session_state.get(f"chk_{i}", True)]

            missing = []
            if not st.session_state.api_key: missing.append("an API key")
            if not st.session_state.uploaded_artifact: missing.append("an artifact")
            if not active_controls: missing.append("at least one control")

            run = st.button("Run audit", type="primary", use_container_width=True, disabled=bool(missing))
            if missing:
                st.markdown(f'<div class="hint">To run the audit, add {esc(", ".join(missing))}.</div>', unsafe_allow_html=True)

            if run:
                with st.spinner(f"Lead Auditor is cross-examining artifact using model '{selected_model}'..."):
                    result = execute_audit(st.session_state.uploaded_artifact, st.session_state.uploaded_artifact_name, active_controls, selected_model)
                    if result:
                        st.session_state.current_audit_result = result
                        st.session_state.audit_history.insert(0, {
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "artifact_name": st.session_state.uploaded_artifact_name,
                            "controls_checked": active_controls,
                            "model_used": selected_model,
                            "result": result
                        })
                        st.rerun()

    # --- RIGHT: VERDICT & CHAT ---
    with col2:
        with card("verdict"):
            card_title("Audit verdict")
            res = st.session_state.current_audit_result
            if not res:
                st.markdown('<div class="empty"><strong>No audit has been run</strong>Load an artifact, confirm the claimed controls, then select Run audit.</div>', unsafe_allow_html=True)
            else:
                status = res.get("audit_status", "REJECTED")
                approved = status == "APPROVED"
                findings = res.get("findings", [])
                failed = count_failed(res)
                st.markdown(
                    '<div class="kpis">'
                    f'<div class="kpi"><div class="kpi-label">Verdict</div><div class="kpi-value">{chip("Approved" if approved else "Rejected", "pass" if approved else "fail")}</div></div>'
                    f'<div class="kpi"><div class="kpi-label">Confidence</div><div class="kpi-value">{esc(str(res.get("confidence_score", "n/a")))}%</div></div>'
                    f'<div class="kpi"><div class="kpi-label">Controls passed</div><div class="kpi-value">{len(findings) - failed} of {len(findings)}</div></div>'
                    f'<div class="kpi"><div class="kpi-label">Failed controls</div><div class="kpi-value">{failed}</div></div>'
                    '</div>'
                    f'<div class="summary"><b>Executive summary</b><br>{esc(str(res.get("executive_summary", "No summary provided.")))}</div>',
                    unsafe_allow_html=True)
                st.markdown("#### Control breakdown")
                for f in findings:
                    render_finding(f)
                st.download_button("Export report (JSON)", json.dumps(res, indent=2), file_name="secure_shift_audit.json", mime="application/json", key="dl_current")

        with card("chat"):
            card_title("Cross-examination", "Challenge findings, submit revised code, or ask the Lead Auditor to clarify a remediation.")
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if prompt := st.chat_input("Ask the Lead Auditor or paste updated code for review..."):
                st.session_state.chat_history.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("Lead Auditor evaluating response..."):
                        reply = execute_chat_followup(prompt, selected_model)
                        if reply:
                            st.markdown(reply)
                            st.session_state.chat_history.append({"role": "assistant", "content": reply})

# ==========================================
# 8. PAGE 2: AUDIT HISTORY
# ==========================================
else:
    page_header("Examination ledger", "Every evaluation run in this session, with the evidence behind each verdict.")
    history = st.session_state.audit_history

    if not history:
        with card("empty"):
            st.markdown('<div class="empty"><strong>No audits recorded yet</strong>Run an audit from Active audit and it will appear here.</div>', unsafe_allow_html=True)
    else:
        with card("ledger"):
            card_title("Runs", f"{len(history)} in this session, newest first.")
            st.dataframe([{
                "Run": len(history) - i,
                "Time": e["timestamp"],
                "Artifact": e["artifact_name"],
                "Model": e.get("model_used", ""),
                "Verdict": e["result"].get("audit_status", "REJECTED").title(),
                "Failed controls": count_failed(e["result"]),
            } for i, e in enumerate(history)], use_container_width=True, hide_index=True)

        for idx, entry in enumerate(history):
            res = entry["result"]
            status = res.get("audit_status", "REJECTED")
            approved = status == "APPROVED"
            with st.expander(f"Run {len(history) - idx}: {entry['artifact_name']} ({status.title()}), {entry['timestamp']}", expanded=(idx == 0)):
                st.markdown(
                    f'{chip(status.title(), "pass" if approved else "fail")} '
                    f'<span class="mono">{esc(entry["timestamp"])} | {esc(entry["artifact_name"])} | {esc(entry.get("model_used", ""))}</span>'
                    f'<div class="summary" style="margin-top:12px"><b>Executive summary</b><br>{esc(str(res.get("executive_summary", "")))}</div>',
                    unsafe_allow_html=True)
                for f in res.get("findings", []):
                    render_finding(f, collapsible=False)
                st.download_button("Export report (JSON)", json.dumps(res, indent=2), file_name=f"secure_shift_run_{len(history) - idx}.json", mime="application/json", key=f"dl_{idx}")
                st.markdown("**Raw evidence**")
                st.json(res, expanded=False)