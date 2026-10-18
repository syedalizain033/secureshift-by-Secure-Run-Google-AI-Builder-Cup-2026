# 🛡️ ComplianceGate AI: End-to-End Data Flow & Architecture Blueprint

This document details the complete data lifecycle of **ComplianceGate AI**, tracing every byte of data from the developer's initial input through backend orchestration, cloud AI examination, and final UI rendering.

---

## 1. High-Level Visual Data Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as Developer / Lead
    participant FE as Streamlit UI (Frontend)
    participant BE as Python Backend Runtime
    participant State as st.session_state (Memory)
    participant Cloud as Google AI Studio API (Gemini 1.5 Pro)

    User->>FE: Uploads Artifact (SQL/Terraform) & Checks Checklist
    FE->>BE: Passes raw string payload & boolean state
    BE->>State: Stores/Updates Session Buffer & Chat History
    BE->>Cloud: HTTPS POST Request (System Prompt + Artifact + Checklist)
    Note over Cloud: Gemini 1.5 Pro performs Zero-Trust<br/>Cross-Examination & RAG Reasoning
    Cloud-->>BE: Returns Strict JSON Response (Verdict, Findings, Diffs)
    BE->>State: Appends Audit Log & Assistant Reply to History
    BE-->>FE: Renders Red/Green Badges & Persistent Chat Log
    FE-->>User: Displays Audit Verdict & Auto-Remediation Code