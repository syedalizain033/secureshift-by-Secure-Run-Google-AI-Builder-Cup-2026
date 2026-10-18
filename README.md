# Secure Shift · Shift-Left GRC Gateway (Demo)

Adversarial AI lead auditor that cross-examines Terraform/SQL artifacts for **IdentityAI** against SOC 2, CCPA and GLBA controls.
Streamlit + Google Gemini, with email/password login and permanent history in Google Cloud Firestore.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI: login gate, workspace, audit history, activity log |
| `auditor.py` | Gemini model catalogue, prompts, response schema, retry and failover |
| `storage.py` | Auth + persistence: Cloud Firestore, or the local SQLite store for tests/offline |
| `config.py` | **All settings, including Firestore** (env vars or `.env`) |
| `.streamlit/config.toml` | Theme and runtime settings |
| `Dockerfile`, `deploy.sh` | Cloud Run image and one-command deploy |
| `firestore.rules`, `firebase.json` | Locks Firestore to server-side access only |
| `tests/` | Headless end-to-end smoke test (85 checks) |
| `logs/` | Test run log, app log, live Gemini API check |

## Run locally (writes to your Firestore)

Requires Python 3.11+ (`brew install python@3.12`) and the `gcloud` CLI.

```bash
/opt/homebrew/bin/python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                       # then fill in GEMINI_API_KEY and FIRESTORE_PROJECT_ID
gcloud auth application-default login      # lets the app reach Firestore as you; no key file
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
streamlit run app.py
```

Your Google account needs `roles/datastore.user` (or Owner/Editor) on the project.
The login footer and the demo ribbon show `Firestore · your-project-id` when connected. If Firestore is unreachable
on a laptop, the app falls back to `data/secure_shift_demo.db` and shows the reason in a red banner.
Set `STORAGE_BACKEND=local` to work offline on purpose.

## Firestore layout

| Path | Contents |
|---|---|
| `accounts/{email}` | Login credentials: `uid`, `email`, salted PBKDF2-SHA256 `pw_hash`, `salt`, `rounds`, `created_at`. Never the password. |
| `users/{uid}` | Profile: `email`, `created_at`, `last_login_at`, `active_artifact_id` |
| `users/{uid}/messages` | Lead Auditor chat history |
| `users/{uid}/events` | Activity log: sign-ins, sign-outs, failovers, errors |
| `users/{uid}/audits` | Audit verdicts |
| `users/{uid}/artifacts` | Submitted files |

Everything under `users/{uid}` is loaded when that user signs in.

## Deploy to Cloud Run

Prerequisites: `gcloud` CLI, a project with billing enabled, and Owner or Editor + IAM Admin rights.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
bash deploy.sh                        # REGION=europe-west1 bash deploy.sh to change region
```

The script enables the APIs, creates a least-privilege runtime service account, stores `GEMINI_API_KEY` and a Streamlit cookie secret in **Secret Manager**, grants its service account `roles/datastore.user` on Firestore, then builds and deploys. It prints the public URL at the end.

Settings it applies: 1 vCPU / 1 GiB, `min-instances=1` (no cold start during judging), session affinity (needed for Streamlit websockets), 60-minute request timeout, gen2 runtime, startup CPU boost.
On Cloud Run the app never falls back to the in-container store (`ALLOW_LOCAL_FALLBACK=false`); if Firestore is unreachable it shows a retry screen.

If Cloud Run builds automatically on every push to `main` instead, `deploy.sh` is not used. Run this once:

```bash
SA=$(gcloud run services describe SERVICE --region REGION --format='value(spec.template.spec.serviceAccountName)')
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID --member "serviceAccount:${SA}" --role roles/datastore.user
gcloud run services update SERVICE --region REGION \
  --update-env-vars STORAGE_BACKEND=firestore,FIRESTORE_PROJECT_ID=YOUR_PROJECT_ID,ALLOW_LOCAL_FALLBACK=false \
  --remove-env-vars FIREBASE_WEB_API_KEY,FIREBASE_PROJECT_ID
```

## Before the competition

- **Enable billing on the Gemini key's project.** The key is on the free tier: 20 requests per model per day, already exhausted for `gemini-3.8-flash` today. Auto-failover stretches this across four models, but a live demo needs paid quota. Gemini 4 Argon and 3.1 Pro only work with billing.
- **Rotate the API key afterwards.** It has been shared in plain text.
- The app is marked **Demo** in the ribbon, sidebar and login card. Set `DEMO_MODE=false` to remove it.

## Tests and logs

```bash
python tests/run_smoke.py     # 85 end-to-end checks, no network needed
```

- `logs/test_run.log`: smoke-test output
- `logs/secure_shift.log`: application log (emails masked, no secrets)
- `logs/gemini_live_check.log`: real API calls made with your key, and the fixes they triggered

On Cloud Run, logs stream to Cloud Logging as structured JSON:
`gcloud run services logs read secure-shift --region us-central1`

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Gemini quota exhausted" | Enable billing, or wait for the daily reset. Keep *Auto-failover* on. |
| Banner says "Firestore is configured but unavailable" | Database not created, wrong `FIRESTORE_PROJECT_ID`/`FIRESTORE_DATABASE`, or the identity lacks `roles/datastore.user`. Locally, rerun `gcloud auth application-default login`. |
| "DefaultCredentialsError" locally | Run `gcloud auth application-default login`. |
| Build fails with a permission error | Grant `roles/run.builder` to `PROJECT_NUMBER-compute@developer.gserviceaccount.com`. |
| Users signed out after a browser refresh | Expected in this demo. Streamlit sessions are per tab; history is kept in the database. |
