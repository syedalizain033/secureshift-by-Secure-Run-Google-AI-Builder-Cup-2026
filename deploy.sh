#!/usr/bin/env bash
# =====================================================================
# Secure Shift - one-command deploy to Google Cloud Run
#
#   bash deploy.sh                      # uses your current gcloud project
#   PROJECT_ID=my-proj REGION=europe-west1 bash deploy.sh
#
# What it does (idempotent - safe to re-run):
#   1. enables the required Google Cloud APIs
#   2. creates a least-privilege runtime service account
#   3. stores GEMINI_API_KEY (+ a Streamlit cookie secret) in Secret Manager
#   4. grants Firestore access when Firebase is configured in .env
#   5. builds the container with Cloud Build and deploys it to Cloud Run
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"

# ---------- load local settings ----------
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-secure-shift}"
MIN_INSTANCES="${MIN_INSTANCES:-1}"     # 1 = no cold starts during the demo
MAX_INSTANCES="${MAX_INSTANCES:-3}"
DEFAULT_MODEL="${DEFAULT_MODEL:-gemini-3.8-flash}"
FIREBASE_WEB_API_KEY="${FIREBASE_WEB_API_KEY:-}"
FIREBASE_PROJECT_ID="${FIREBASE_PROJECT_ID:-}"
FIREBASE_SERVICE_ACCOUNT_FILE="${FIREBASE_SERVICE_ACCOUNT_FILE:-./firebase-service-account.json}"

GEMINI_SECRET="${SERVICE}-gemini-key"
COOKIE_SECRET="${SERVICE}-cookie-secret"
FIREBASE_SA_SECRET="${SERVICE}-firebase-sa"
RUN_SA_NAME="${SERVICE}-run"

say()  { printf "\n\033[1;34m==> %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m[warn] %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m[error] %s\033[0m\n" "$*" >&2; exit 1; }

# ---------- preflight ----------
command -v gcloud >/dev/null || die "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
[[ -n "$PROJECT_ID" ]] || die "No project. Run: gcloud config set project YOUR_PROJECT_ID (or PROJECT_ID=... bash deploy.sh)"
[[ -n "${GEMINI_API_KEY:-}" ]] || die "GEMINI_API_KEY is empty. Put it in .env"
gcloud auth print-access-token >/dev/null 2>&1 || die "Not logged in. Run: gcloud auth login"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUN_SA="${RUN_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
FIREBASE_ON=false
[[ -n "$FIREBASE_WEB_API_KEY" && -n "$FIREBASE_PROJECT_ID" ]] && FIREBASE_ON=true

say "Project ${PROJECT_ID} (${PROJECT_NUMBER}) · region ${REGION} · service ${SERVICE} · firebase=${FIREBASE_ON}"

if [[ "$FIREBASE_ON" != true ]]; then
  warn "Firebase is not configured - the app will use the local demo store inside the container."
  warn "History then lives in one instance and is lost on restart. Forcing MAX_INSTANCES=1."
  MAX_INSTANCES=1
  [[ "$MIN_INSTANCES" -gt 1 ]] && MIN_INSTANCES=1
fi

# ---------- APIs ----------
say "Enabling APIs (first run can take a minute)"
APIS="run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com"
[[ "$FIREBASE_ON" == true && "$FIREBASE_PROJECT_ID" == "$PROJECT_ID" ]] && APIS="$APIS firestore.googleapis.com identitytoolkit.googleapis.com"
# shellcheck disable=SC2086
gcloud services enable $APIS --project "$PROJECT_ID"

# ---------- service accounts ----------
say "Runtime service account ${RUN_SA}"
if ! gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUN_SA_NAME" --project "$PROJECT_ID" \
    --display-name "Secure Shift Cloud Run runtime"
  echo "   waiting for the new service account to propagate..."
  for _ in $(seq 1 12); do
    gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT_ID" >/dev/null 2>&1 && break
    sleep 5
  done
  sleep 15  # IAM bindings on brand-new accounts can still fail for a few seconds
fi

say "Allowing Cloud Build to build from source"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${BUILD_SA}" \
  --role roles/run.builder --condition=None --quiet >/dev/null \
  || warn "Could not grant roles/run.builder to ${BUILD_SA} (needs Owner/IAM Admin). If the build fails with a permission error, ask an admin to grant it."

# ---------- secrets ----------
upsert_secret() {  # name value
  local name="$1" value="$2"
  if ! gcloud secrets describe "$name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    printf "%s" "$value" | gcloud secrets create "$name" --project "$PROJECT_ID" \
      --replication-policy automatic --data-file=- >/dev/null
    echo "   created secret ${name}"
  elif [[ "$(gcloud secrets versions access latest --secret "$name" --project "$PROJECT_ID" 2>/dev/null || true)" != "$value" ]]; then
    printf "%s" "$value" | gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=- >/dev/null
    echo "   updated secret ${name}"
  else
    echo "   secret ${name} unchanged"
  fi
  gcloud secrets add-iam-policy-binding "$name" --project "$PROJECT_ID" \
    --member "serviceAccount:${RUN_SA}" --role roles/secretmanager.secretAccessor --quiet >/dev/null
}

say "Storing secrets in Secret Manager"
upsert_secret "$GEMINI_SECRET" "$GEMINI_API_KEY"
if ! gcloud secrets describe "$COOKIE_SECRET" --project "$PROJECT_ID" >/dev/null 2>&1; then
  upsert_secret "$COOKIE_SECRET" "$(openssl rand -hex 32)"
else
  gcloud secrets add-iam-policy-binding "$COOKIE_SECRET" --project "$PROJECT_ID" \
    --member "serviceAccount:${RUN_SA}" --role roles/secretmanager.secretAccessor --quiet >/dev/null
fi
SECRETS="GEMINI_API_KEY=${GEMINI_SECRET}:latest,STREAMLIT_SERVER_COOKIE_SECRET=${COOKIE_SECRET}:latest"

# ---------- Firebase / Firestore access ----------
if [[ "$FIREBASE_ON" == true ]]; then
  if [[ "$FIREBASE_PROJECT_ID" == "$PROJECT_ID" ]]; then
    say "Granting Firestore access (same project - no key file needed)"
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUN_SA}" \
      --role roles/datastore.user --condition=None --quiet >/dev/null
  elif [[ -f "$FIREBASE_SERVICE_ACCOUNT_FILE" ]]; then
    say "Firebase lives in another project - uploading its service-account key as a secret"
    upsert_secret "$FIREBASE_SA_SECRET" "$(cat "$FIREBASE_SERVICE_ACCOUNT_FILE")"
    SECRETS="${SECRETS},FIREBASE_SERVICE_ACCOUNT_JSON=${FIREBASE_SA_SECRET}:latest"
  else
    die "FIREBASE_PROJECT_ID (${FIREBASE_PROJECT_ID}) differs from PROJECT_ID (${PROJECT_ID}) and ${FIREBASE_SERVICE_ACCOUNT_FILE} was not found."
  fi
fi

# ---------- deploy ----------
say "Building and deploying ${SERVICE} (Cloud Build, ~3-5 minutes)"
ENV_VARS="^@^DEMO_MODE=true@DEFAULT_MODEL=${DEFAULT_MODEL}@LOG_LEVEL=INFO@FIREBASE_WEB_API_KEY=${FIREBASE_WEB_API_KEY}@FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}"
# With Firebase on, never silently fall back to per-container storage; a transient error is retried instead.
[[ "$FIREBASE_ON" == true ]] && ENV_VARS="${ENV_VARS}@ALLOW_LOCAL_FALLBACK=false"

gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --service-account "$RUN_SA" \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 \
  --memory 1Gi \
  --cpu-boost \
  --execution-environment gen2 \
  --timeout 3600 \
  --concurrency 40 \
  --session-affinity \
  --min-instances "$MIN_INSTANCES" \
  --max-instances "$MAX_INSTANCES" \
  --set-env-vars "$ENV_VARS" \
  --set-secrets "$SECRETS" \
  --labels app=secure-shift,stage=demo \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format='value(status.url)')"

# ---------- public access check ----------
# Corporate org policies (domain-restricted sharing) can block the allUsers binding -> HTTP 403 for judges.
say "Checking public access"
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${URL}/_stcore/health" || echo 000)"
if [[ "$CODE" != "200" ]]; then
  warn "Public health check returned HTTP ${CODE}. Retrying with the invoker IAM check disabled..."
  if gcloud run services update "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --no-invoker-iam-check --quiet; then
    sleep 10
    CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${URL}/_stcore/health" || echo 000)"
  fi
  [[ "$CODE" == "200" ]] || warn "Still HTTP ${CODE}. An organisation policy is blocking public access - deploy to a project outside the corporate org, or ask an admin to allow it."
fi
[[ "$CODE" == "200" ]] && echo "   public health check OK"

say "Deployed: ${URL}"
echo "   Logs:  gcloud run services logs read ${SERVICE} --region ${REGION} --project ${PROJECT_ID} --limit 100"
echo "   Tail:  gcloud beta run services logs tail ${SERVICE} --region ${REGION} --project ${PROJECT_ID}"
