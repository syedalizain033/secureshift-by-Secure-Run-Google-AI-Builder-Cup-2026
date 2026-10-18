# Secure Shift · Shift-Left GRC Gateway (Demo)

Adversarial AI lead auditor that cross-examines Terraform/SQL artifacts for **IdentityAI** against SOC 2, CCPA and GLBA controls.
Streamlit + Google Gemini, with email/password login and permanent history in Firebase.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI: login gate, workspace, audit history, activity log |
| `auditor.py` | Gemini model catalogue, prompts, response schema, retry and failover |
| `storage.py` | Auth + persistence: Firebase (Auth REST + Firestore) or the local SQLite demo store |
| `config.py` | **All settings, including the Firebase block** (env vars or `.env`) |
| `.streamlit/config.toml` | Theme and runtime settings |
| `Dockerfile`, `deploy.sh` | Cloud Run image and one-command deploy |
| `firestore.rules`, `firebase.json` | Locks Firestore to server-side access only |
| `tests/` | Headless end-to-end smoke test (78 checks) |
| `logs/` | Test run log, app log, live Gemini API check |

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

`.env` already contains your `GEMINI_API_KEY`. Until Firebase is configured, accounts and history live in `data/secure_shift_demo.db`.

## Connect Firebase (what I need from you)

1. **Firebase project.** Ideally the same Google Cloud project you deploy Cloud Run to. Send the **Project ID**.
2. **Web API Key.** Firebase console → Project settings → General → *Your apps*. Add a Web app if there is none, then copy `apiKey`.
3. **Enable Email/Password.** Authentication → Sign-in method → Email/Password → Enable.
4. **Create Firestore.** Firestore Database → Create database → *Native mode*, production rules, region near your Cloud Run region (e.g. `nam5` / `us-central1`).
5. **Local testing only:** Project settings → Service accounts → *Generate new private key*. Save it as `firebase-service-account.json` next to `app.py`. Cloud Run in the same project does not need this file.
6. *(Optional)* `firebase deploy --only firestore:rules` to apply `firestore.rules`.

Then put the two values in `.env` (or directly in the `FIREBASE` block of `config.py`):

```
FIREBASE_WEB_API_KEY=AIza...
FIREBASE_PROJECT_ID=your-project-id
```

The app switches to Firebase automatically on the next start. The login footer and the demo ribbon show `Firebase · your-project-id`.
If the API key has *application restrictions* (HTTP referrers), allow server use or remove the restriction, because sign-in calls come from the server.

Firestore layout: `users/{uid}` profile, with sub-collections `artifacts`, `audits`, `messages` and `events`.

## Deploy to Cloud Run

Prerequisites: `gcloud` CLI, a project with billing enabled, and Owner or Editor + IAM Admin rights.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
bash deploy.sh                        # REGION=europe-west1 bash deploy.sh to change region
```

The script enables the APIs, creates a least-privilege runtime service account, stores `GEMINI_API_KEY` and a Streamlit cookie secret in **Secret Manager**, grants Firestore access, then builds and deploys. It prints the public URL at the end.

Settings it applies: 1 vCPU / 1 GiB, `min-instances=1` (no cold start during judging), session affinity (needed for Streamlit websockets), 60-minute request timeout, gen2 runtime, startup CPU boost.
Without Firebase it forces `max-instances=1`, because the local store lives inside one container and is wiped on restart.

## Before the competition

- **Enable billing on the Gemini key's project.** The key is on the free tier: 20 requests per model per day, already exhausted for `gemini-3.8-flash` today. Auto-failover stretches this across four models, but a live demo needs paid quota. Gemini 4 Argon and 3.1 Pro only work with billing.
- **Rotate the API key afterwards.** It has been shared in plain text.
- The app is marked **Demo** in the ribbon, sidebar and login card. Set `DEMO_MODE=false` to remove it.

## Tests and logs

```bash
python tests/run_smoke.py     # 78 end-to-end checks, no network needed
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
| Banner says "Firebase is configured but unavailable" | Firestore database not created, or the runtime service account lacks `roles/datastore.user`. |
| "Email/password sign-in is disabled" | Enable the provider in Firebase Authentication. |
| Build fails with a permission error | Grant `roles/run.builder` to `PROJECT_NUMBER-compute@developer.gserviceaccount.com`. |
| Users signed out after a browser refresh | Expected in this demo. Streamlit sessions are per tab; history is kept in the database. |
