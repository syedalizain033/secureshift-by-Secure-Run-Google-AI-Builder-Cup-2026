"""
Secure Shift - Gemini Lead Auditor.

* Model catalogue verified against the live Gemini API (October 2026).
* Structured JSON output enforced with a response schema.
* Retries transient 5xx errors and fails over to backup models on quota (429),
  overload (503) or retired models (404), so a demo never dead-ends.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types
except ImportError:  # pragma: no cover - surfaced in the UI
    genai = None
    genai_errors = None
    types = None

log = logging.getLogger("secure_shift.auditor")


# ======================================================================
# Model catalogue
# ======================================================================
@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    tier: str  # Stable | Preview | Alias
    note: str


MODEL_CATALOG: list[ModelInfo] = [
    ModelInfo("gemini-3.8-flash", "Gemini 3.8 Flash", "Stable", "Recommended. Most capable Flash model, 1M context."),
    ModelInfo("gemini-4-argon", "Gemini 4 Argon", "Stable", "Flagship reasoning model. Requires a paid (billing-enabled) key."),
    ModelInfo("gemini-3.7-flash", "Gemini 3.7 Flash", "Stable", "Previous Flash release."),
    ModelInfo("gemini-3.6-flash", "Gemini 3.6 Flash", "Stable", "Balanced speed and quality."),
    ModelInfo("gemini-3.5-flash", "Gemini 3.5 Flash", "Stable", "Earlier 3.5-generation Flash."),
    ModelInfo("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "Stable", "Fastest and lowest cost."),
    ModelInfo("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "Stable", "Low-cost, high-throughput."),
    ModelInfo("gemini-3.1-pro-preview", "Gemini 3.1 Pro", "Preview", "Deep reasoning. Requires a paid key."),
    ModelInfo("gemini-3-flash-preview", "Gemini 3 Flash", "Preview", "Preview model; may be rate-limited at peak."),
    ModelInfo("gemini-flash-latest", "Gemini Flash (latest)", "Alias", "Always points at the newest Flash."),
    ModelInfo("gemini-flash-lite-latest", "Gemini Flash-Lite (latest)", "Alias", "Always points at the newest Flash-Lite."),
    ModelInfo("gemini-pro-latest", "Gemini Pro (latest)", "Alias", "Always points at the newest Pro. Requires a paid key."),
]
CATALOG_BY_ID = {m.id: m for m in MODEL_CATALOG}
DEFAULT_MODEL = "gemini-3.8-flash"
# Distinct underlying models (each has its own quota bucket).
FAILOVER_CHAIN = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


def model_label(model_id: str) -> str:
    info = CATALOG_BY_ID.get(model_id)
    return f"{info.label} · {info.tier}" if info else model_id


def fetch_available_models(api_key: str) -> list[str] | None:
    """Model ids this key can call with generateContent, or None if the lookup fails."""
    if not (genai and api_key):
        return None
    try:
        client = genai.Client(api_key=api_key)
        names = []
        for m in client.models.list(config={"page_size": 1000}):
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions:
                names.append(m.name.replace("models/", ""))
        log.info("Model discovery: %d generateContent models visible to this key", len(names))
        return names
    except Exception as exc:
        log.warning("Model discovery failed: %s", exc)
        return None


def model_options(available: list[str] | None) -> list[str]:
    if not available:
        return [m.id for m in MODEL_CATALOG]
    opts = [m.id for m in MODEL_CATALOG if m.id in available]
    return opts or [m.id for m in MODEL_CATALOG]


# ======================================================================
# Controls & prompts
# ======================================================================
CONTROLS = [
    {
        "id": "SOC2-CC6.1",
        "title": "PII/SSN field-level AES-256 encryption",
        "framework": "SOC 2 Type II",
        "tip": "Sensitive PII such as SSNs must be encrypted at field level before it reaches persistence.",
    },
    {
        "id": "CCPA-1798",
        "title": "24-hour temp image auto-deletion",
        "framework": "CCPA § 1798.100",
        "tip": "Biometric snapshots and government IDs must expire within 24 hours of KYC resolution.",
    },
    {
        "id": "SOC2-CC6.3",
        "title": "Customer-managed encryption keys (CMEK)",
        "framework": "SOC 2 Type II",
        "tip": "Storage must use customer-managed KMS/Vault keys, not provider-default keys.",
    },
]
CONTROL_IDS = [c["id"] for c in CONTROLS]

LEAD_AUDITOR_SYSTEM_PROMPT = """You are the Autonomous Principal GRC Auditor for "Secure Shift", an adversarial regulatory compliance gateway.
You cross-examine architecture and code artifacts submitted for "IdentityAI", an enterprise eKYC identity-verification microservice.

Control catalogue
1. SOC2-CC6.1 - PII/SSN field-level AES-256 encryption at rest. Look for plaintext PII columns, missing pgcrypto / pgp_sym_encrypt, or no application-level envelope encryption.
2. CCPA-1798 - 24-hour auto-deletion of temporary biometric images and government IDs. Look for explicit TTLs, S3/GCS lifecycle expiration rules, or scheduled teardown jobs.
3. SOC2-CC6.3 - Customer-managed encryption keys (CMEK) via AWS KMS, Cloud KMS or HashiCorp Vault. Provider-default keys (SSE-S3 "AES256", Google-managed keys) do NOT satisfy this control.

Audit protocol
- Zero trust: developers claim these controls are implemented. Trust nothing that is not evidenced in the artifact.
- Evaluate exactly the controls listed in "developer_claimed_controls": one finding per control, using the exact control_id.
- A claimed control that is not evidenced in the artifact is a FAIL.
- audit_status is REJECTED if any finding is FAIL. APPROVED only when every evaluated control is strictly evidenced.
- confidence_score is an integer from 0 to 100 describing how conclusive the evidence is.
- severity: CRITICAL for exposed regulated data, HIGH for a missing mandatory safeguard, MEDIUM or LOW for partial or hygiene gaps. Use LOW for PASS findings.
- reason: cite the exact resource, table, column or setting that proves the verdict.
- remediation_fix: a concrete, copy-pasteable patch (SQL, Terraform/HCL, YAML...), not prose. For PASS findings give a one-line hardening tip.
- remediation_language: the language of remediation_fix (sql, hcl, yaml, json, python, bash or text).
Respond only with JSON that matches the response schema."""

CHAT_AUDITOR_SYSTEM_PROMPT = """You are the Lead Auditor of Secure Shift, speaking with the lead developer of IdentityAI.
Keep a formal, zero-trust, highly technical auditor tone.
You have the submitted artifact, the latest audit findings and the regulatory standards (SOC 2, CCPA, GLBA).
Give precise remediation guidance, point out vulnerabilities, and verify any code patches the developer submits.
Use Markdown. Put code in fenced blocks with a language tag. Be concise and specific."""


def _audit_schema(claimed: list[str]) -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "audit_status": {"type": "STRING", "enum": ["APPROVED", "REJECTED"]},
            "confidence_score": {"type": "INTEGER"},
            "executive_summary": {"type": "STRING"},
            "findings": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "control_id": {"type": "STRING", "enum": claimed or CONTROL_IDS},
                        "control_title": {"type": "STRING"},
                        "verdict": {"type": "STRING", "enum": ["PASS", "FAIL"]},
                        "severity": {"type": "STRING", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
                        "reason": {"type": "STRING"},
                        "remediation_fix": {"type": "STRING"},
                        "remediation_language": {"type": "STRING"},
                    },
                    "required": ["control_id", "control_title", "verdict", "severity", "reason", "remediation_fix"],
                },
            },
        },
        "required": ["audit_status", "confidence_score", "executive_summary", "findings"],
    }


# ======================================================================
# Results
# ======================================================================
class AuditorError(Exception):
    def __init__(self, message: str, attempts: list[dict] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


@dataclass
class GenResult:
    text: str
    model_used: str
    latency_ms: int
    attempts: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


_LANG_ALIASES = {"terraform": "hcl", "tf": "hcl", "postgresql": "sql", "postgres": "sql", "yml": "yaml", "shell": "bash", "sh": "bash"}
_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def _guess_language(code: str) -> str:
    c = code or ""
    if re.search(r'\bresource\s+"|\bprovider\s+"|\bmodule\s+"', c):
        return "hcl"
    if re.search(r"\b(CREATE|ALTER|SELECT|INSERT|UPDATE)\b", c, re.I):
        return "sql"
    return "text"


def normalize_result(raw: dict, claimed: list[str]) -> dict:
    """Coerce model output into a consistent, self-consistent audit record."""
    findings = []
    for f in raw.get("findings") or []:
        if not isinstance(f, dict):
            continue
        verdict = "PASS" if str(f.get("verdict", "")).upper() == "PASS" else "FAIL"
        sev = str(f.get("severity") or "").upper()
        if sev not in _SEVERITIES:
            sev = "LOW" if verdict == "PASS" else "HIGH"
        fix = str(f.get("remediation_fix") or "").strip()
        lang = str(f.get("remediation_language") or "").strip().lower()
        lang = _LANG_ALIASES.get(lang, lang) or _guess_language(fix)
        findings.append(
            {
                "control_id": str(f.get("control_id", "UNKNOWN")).strip().strip("[]"),
                "control_title": str(f.get("control_title", "")).strip(),
                "verdict": verdict,
                "severity": sev,
                "reason": str(f.get("reason", "")).strip(),
                "remediation_fix": fix,
                "remediation_language": lang,
            }
        )
    failed = sum(1 for f in findings if f["verdict"] != "PASS")
    model_status = str(raw.get("audit_status", "")).upper()
    status = "APPROVED" if (findings and failed == 0 and model_status == "APPROVED") else "REJECTED"
    try:
        conf = float(raw.get("confidence_score", 0))
        conf = int(round(conf * 100 if 0 < conf <= 1 else conf))
    except (TypeError, ValueError):
        conf = 0
    return {
        "audit_status": status,
        "confidence_score": max(0, min(100, conf)),
        "executive_summary": str(raw.get("executive_summary") or "No summary provided.").strip(),
        "findings": findings,
        "failed_count": failed,
        "claimed_controls": claimed,
    }


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text or "", re.S)
        if match:
            return json.loads(match.group(0))
        raise


# ======================================================================
# Gemini calls with retry + failover
# ======================================================================
def _friendly(code, message: str) -> str:
    msg = message or ""
    if code in (400, 401, 403) and ("API key" in msg or "API_KEY" in msg or code in (401, 403)):
        return "The Gemini API key was rejected. Check GEMINI_API_KEY (or the key override in the sidebar)."
    if code == 429:
        return "Gemini quota exhausted for this key. Free-tier keys allow about 20 requests per model per day; enable billing on the Google Cloud project for production use."
    if code in (500, 502, 503, 504):
        return "Gemini is temporarily overloaded. Try again in a moment or pick another model."
    if code == 404:
        return "The selected model is not available to this API key."
    return f"Gemini request failed ({code}): {msg[:200]}"


def _is_gemini3plus(model: str) -> bool:
    return model.startswith(("gemini-3", "gemini-4")) or model.endswith("-latest")


def _config(model: str, system: str, temperature: float, schema: dict | None = None):
    kwargs = {"system_instruction": system}
    # Google recommends the default temperature for Gemini 3+ (lower values can cause looping).
    if not _is_gemini3plus(model):
        kwargs["temperature"] = temperature
    if schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = schema
    return types.GenerateContentConfig(**kwargs)


def _generate(api_key: str, model: str, contents, make_config, failover: bool, op: str) -> GenResult:
    if genai is None:
        raise AuditorError("The google-genai package is not installed. Run: pip install -r requirements.txt")
    if not api_key:
        raise AuditorError("No Gemini API key configured. Set GEMINI_API_KEY or use the key override in the sidebar.")

    client = genai.Client(api_key=api_key)
    chain = [model] + ([m for m in FAILOVER_CHAIN if m != model] if failover else [])
    attempts: list[dict] = []

    for m in chain:
        for retry in range(2):  # one retry on transient 5xx per model
            t0 = time.perf_counter()
            try:
                resp = client.models.generate_content(model=m, contents=contents, config=make_config(m))
                text = resp.text
                ms = int((time.perf_counter() - t0) * 1000)
                if not text:
                    reason = ""
                    try:
                        reason = str(resp.candidates[0].finish_reason)
                    except Exception:
                        pass
                    attempts.append({"model": m, "status": "empty", "latency_ms": ms, "error": f"Empty response {reason}".strip()})
                    log.warning("%s: %s returned an empty response %s", op, m, reason)
                    break
                usage = {}
                um = getattr(resp, "usage_metadata", None)
                if um is not None:
                    usage = {
                        "prompt_tokens": getattr(um, "prompt_token_count", None),
                        "output_tokens": getattr(um, "candidates_token_count", None),
                        "total_tokens": getattr(um, "total_token_count", None),
                    }
                attempts.append({"model": m, "status": "ok", "latency_ms": ms})
                log.info("%s ok: model=%s latency_ms=%d tokens=%s attempts=%d", op, m, ms, usage.get("total_tokens"), len(attempts))
                return GenResult(text=text, model_used=m, latency_ms=ms, attempts=attempts, usage=usage)
            except Exception as exc:
                ms = int((time.perf_counter() - t0) * 1000)
                is_api = genai_errors is not None and isinstance(exc, genai_errors.APIError)
                code = getattr(exc, "code", None) if is_api else None
                message = (getattr(exc, "message", None) or str(exc)) if is_api else str(exc)
                attempts.append({"model": m, "status": code or type(exc).__name__, "latency_ms": ms, "error": str(message)[:300]})
                log.warning("%s failed: model=%s code=%s msg=%s", op, m, code, str(message)[:200])

                if code in (401, 403) or (code == 400 and "API key" in str(message)):
                    raise AuditorError(_friendly(code, message), attempts) from exc
                if code in (500, 502, 503, 504) and retry == 0:
                    time.sleep(1.5)
                    continue
                break  # 429 / 404 / 400 / 5xx-after-retry / network -> next model

    last = attempts[-1] if attempts else {}
    code = last.get("status")
    raise AuditorError(_friendly(code if isinstance(code, int) else None, last.get("error", "")), attempts)


def run_audit(api_key: str, model: str, artifact_name: str, artifact_code: str, claimed: list[str], failover: bool = True) -> dict:
    payload = {
        "target_application": "IdentityAI (eKYC Platform)",
        "file_analyzed": artifact_name,
        "developer_claimed_controls": claimed,
        "submitted_artifact_code": artifact_code,
    }
    prompt = "Perform an audit examination on the following payload:\n```json\n" + json.dumps(payload, indent=2) + "\n```"
    schema = _audit_schema(claimed)
    gen = _generate(
        api_key, model, prompt,
        lambda m: _config(m, LEAD_AUDITOR_SYSTEM_PROMPT, 0.1, schema),
        failover, "audit",
    )
    try:
        raw = _parse_json(gen.text)
    except (json.JSONDecodeError, ValueError) as exc:
        log.error("audit: model %s returned invalid JSON: %s", gen.model_used, gen.text[:300])
        raise AuditorError("The model returned an unreadable verdict. Run the audit again.", gen.attempts) from exc
    return {
        "result": normalize_result(raw, claimed),
        "model_used": gen.model_used,
        "latency_ms": gen.latency_ms,
        "attempts": gen.attempts,
        "usage": gen.usage,
    }


def run_chat(api_key: str, model: str, artifact: dict | None, audit: dict | None, history: list[dict], user_message: str, failover: bool = True, max_turns: int = 30) -> dict:
    if genai is None:
        raise AuditorError("The google-genai package is not installed. Run: pip install -r requirements.txt")
    code = (artifact or {}).get("content", "")
    if len(code) > 60_000:
        code = code[:60_000] + "\n... [truncated]"
    findings = json.dumps((audit or {}).get("result", {}), indent=2)[:20_000] if audit else "No audit has been run yet."
    primer = (
        "AUDIT CONTEXT\n"
        f"- Target: IdentityAI (eKYC)\n"
        f"- File: {(artifact or {}).get('name', 'none')}\n"
        f"- Latest audit verdict: {((audit or {}).get('result') or {}).get('audit_status', 'No audit run yet')}\n\n"
        f"Latest audit findings (JSON):\n{findings}\n\n"
        f"Submitted artifact:\n```\n{code}\n```"
    )
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=primer)]),
        types.Content(role="model", parts=[types.Part.from_text(text="Understood. Lead Auditor ready to cross-examine artifacts and remediations.")]),
    ]
    for msg in history[-max_turns:]:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=str(msg.get("content", "")))]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

    gen = _generate(
        api_key, model, contents,
        lambda m: _config(m, CHAT_AUDITOR_SYSTEM_PROMPT, 0.3),
        failover, "chat",
    )
    return {"text": gen.text, "model_used": gen.model_used, "latency_ms": gen.latency_ms, "attempts": gen.attempts, "usage": gen.usage}
