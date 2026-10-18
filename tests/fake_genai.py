"""Fake google.genai SDK. Responses replay a real gemini-3.5-flash-lite audit captured on 2026-10-18."""

import json
import sys
import types as _t

REAL_AUDIT_JSON = {
    "audit_status": "REJECTED",
    "confidence_score": 100,
    "executive_summary": "The audit of Secure Shift's submitted artifact code resulted in a REJECTED status due to critical non-compliance issues across all three mandatory controls.",
    "findings": [
        {"control_id": "SOC2-CC6.1", "control_title": "PII/SSN field-level AES-256 encryption at rest", "verdict": "FAIL",
         "reason": "The database schema defines 'ssn_plaintext' as an unencrypted VARCHAR(11) column.",
         "remediation_fix": "ALTER TABLE ekyc_id_verifications ADD COLUMN ssn_encrypted BYTEA;", "remediation_language": "sql", "severity": "CRITICAL"},
        {"control_id": "CCPA-1798", "control_title": "24-hour temp image auto-deletion", "verdict": "FAIL",
         "reason": "No lifecycle rule for auto-deletion after 24 hours.",
         "remediation_fix": 'resource "aws_s3_bucket_lifecycle_configuration" "ttl" { rule { expiration { days = 1 } } }', "remediation_language": "terraform", "severity": "HIGH"},
        {"control_id": "[SOC2-CC6.3]", "control_title": "CMEK via AWS KMS or Vault", "verdict": "fail",
         "reason": "sse_algorithm is AES256 (SSE-S3) instead of aws:kms.",
         "remediation_fix": 'sse_algorithm = "aws:kms"\nkms_master_key_id = aws_kms_key.ekyc.arn', "severity": "high"},
    ],
}

CALLS = []
# model -> list of behaviours consumed in order; each is ("ok", text) or ("err", code, message)
SCRIPT = {}
AVAILABLE = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-4-argon", "gemma-4-31b-it"]


class APIError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{code} {message}")
        self.code = code
        self.message = message
        self.status = "ERR"


errors = _t.ModuleType("google.genai.errors")
errors.APIError = APIError


class GenerateContentConfig:
    def __init__(self, **kw):
        self.kw = kw


class Part:
    def __init__(self, text):
        self.text = text

    @classmethod
    def from_text(cls, text):
        return cls(text)


class Content:
    def __init__(self, role, parts):
        assert role in ("user", "model"), role
        self.role = role
        self.parts = parts


types = _t.ModuleType("google.genai.types")
types.GenerateContentConfig = GenerateContentConfig
types.Part = Part
types.Content = Content


class _Resp:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = _t.SimpleNamespace(prompt_token_count=258, candidates_token_count=545, total_token_count=803)
        self.candidates = [_t.SimpleNamespace(finish_reason="STOP")]


class _Models:
    def generate_content(self, model, contents, config):
        CALLS.append({"model": model, "config": config.kw, "contents": contents})
        queue = SCRIPT.get(model) or SCRIPT.get("*") or [("ok", None)]
        beh = queue.pop(0) if len(queue) > 1 else queue[0]
        if beh[0] == "err":
            raise APIError(beh[1], beh[2])
        if beh[1] is not None:
            return _Resp(beh[1])
        if config.kw.get("response_mime_type") == "application/json":
            return _Resp(json.dumps(REAL_AUDIT_JSON))
        return _Resp("**Finding SOC2-CC6.1** is critical.\n\n```sql\nALTER TABLE ekyc_id_verifications DROP COLUMN ssn_plaintext;\n```")

    def list(self, config=None):
        return [_t.SimpleNamespace(name=f"models/{m}", supported_actions=["generateContent", "countTokens"]) for m in AVAILABLE] + [
            _t.SimpleNamespace(name="models/gemini-3.8-live", supported_actions=["bidiGenerateContent"])]


class Client:
    def __init__(self, api_key=None, **k):
        assert api_key, "api key required"
        self.models = _Models()


genai = _t.ModuleType("google.genai")
genai.Client = Client
genai.errors = errors
genai.types = types


def install():
    try:
        import google  # namespace package (protobuf provides it)
    except ImportError:
        google = _t.ModuleType("google")
        google.__path__ = []
        sys.modules["google"] = google

    google.genai = genai
    sys.modules["google.genai"] = genai
    sys.modules["google.genai.errors"] = errors
    sys.modules["google.genai.types"] = types
