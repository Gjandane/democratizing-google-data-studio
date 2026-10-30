#!/usr/bin/env bash
# Set up the GCP resources (idempotent) and deploy Cloud Run service dss-frontend from the root
# Dockerfile (contracts/conventions.md, Cloud deployment). Run from anywhere in bash:
#   bash deploy/deploy.sh --dry-run   # print every gcloud command, run none (except the guard)
#   bash deploy/deploy.sh             # set up and deploy
# Reads the root .env by parsing it (never `source`). Secret values never reach the output.
set -euo pipefail
# Git Bash: keep MSYS from rewriting /paths in our gcloud args (httpGet.path=/api/health, /data);
# only these prefixes, since the SDK's gcloud wrapper needs its own path converted.
export MSYS2_ARG_CONV_EXCL='httpGet.;volume=;^|^'

SERVICE=dss-frontend
RUNTIME_SA_NAME=dss-runtime

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "deploy.sh: unknown argument: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { echo "deploy.sh: $*" >&2; exit 1; }

# --- .env: KEY=VALUE lines, whitespace stripped, one pair of surrounding quotes removed ---
declare -A ENV=()
[[ -f .env ]] || die "no .env at $ROOT (copy .env.example and fill it in)"
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
  [[ "$line" == *=* ]] || continue
  key="${line%%=*}"; value="${line#*=}"
  key="${key#"${key%%[![:space:]]*}"}"; key="${key%"${key##*[![:space:]]}"}"
  key="${key#export }"
  value="${value#"${value%%[![:space:]]*}"}"; value="${value%"${value##*[![:space:]]}"}"
  if [[ ${#value} -ge 2 && ( ( "$value" == \"*\" ) || ( "$value" == \'*\' ) ) ]]; then
    value="${value:1:${#value}-2}"
  fi
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && ENV["$key"]="$value"
done < .env
env_get() { printf '%s' "${ENV[$1]:-${2:-}}"; }

PROJECT="$(env_get GCP_PROJECT_ID)"
REGION="$(env_get GCP_REGION asia-southeast1)"
BQ_DATASET="$(env_get BQ_DATASET dss_demo)"
BQ_LOCATION="$(env_get BQ_LOCATION US)"
GCS_BUCKET="$(env_get GCS_BUCKET)"
GCS_BUCKET="${GCS_BUCKET#gs://}"; GCS_BUCKET="${GCS_BUCKET%%/*}"

[[ -n "$PROJECT" ]] || die "GCP_PROJECT_ID is empty in .env"
[[ "$REGION" == asia-southeast1 ]] || die "GCP_REGION is '$REGION'; dss-frontend lives in asia-southeast1; refusing"
[[ -n "$(env_get GOOGLE_API_KEY)" ]] || die "GOOGLE_API_KEY is empty in .env"
# DSS_PUBLIC (conventions 1.6): 1 = open link, no gate; empty = gated (Google sign-in, code for scripts).
PUBLIC="$(env_get DSS_PUBLIC)"
[[ -z "$PUBLIC" || "$PUBLIC" == 1 ]] || die "DSS_PUBLIC in .env must be 1 (open link) or empty (gated); refusing to deploy"
token="$(env_get DSS_AGENT_TOKEN)"
(( ${#token} >= 24 )) || die "DSS_AGENT_TOKEN in .env must be at least 24 characters; refusing to deploy"
if [[ -z "$PUBLIC" ]]; then
  code="$(env_get DSS_ACCESS_CODE)"
  (( ${#code} >= 12 )) || die "DSS_ACCESS_CODE in .env must be at least 12 characters when gated; refusing to deploy"
fi
unset code token
# The guard's expected values live only in .env (the repo is public).
EXPECTED_PROJECT_NUMBER="$(env_get GCP_PROJECT_NUMBER)"
EXPECTED_URL="$(env_get DSS_AGENT_SERVER)"; EXPECTED_URL="${EXPECTED_URL%/}"
[[ -n "$EXPECTED_PROJECT_NUMBER" ]] || die "GCP_PROJECT_NUMBER is empty in .env; refusing"
[[ -n "$EXPECTED_URL" ]] || die "DSS_AGENT_SERVER is empty in .env; refusing"
if [[ -n "$PUBLIC" ]]; then
  # Open link: the backend refuses to start with a code or client id set, so neither is deployed.
  OAUTH_CLIENT_ID=""; SIGNIN_ALLOW=""
  SECRETS=(GOOGLE_API_KEY DSS_AGENT_TOKEN)
else
  # Gated: Google sign-in is the gate, so no client id, no deploy (the dry run only warns).
  OAUTH_CLIENT_ID="$(env_get GOOGLE_OAUTH_CLIENT_ID)"
  SIGNIN_ALLOW="$(env_get DSS_SIGNIN_ALLOW)"
  if [[ -z "$OAUTH_CLIENT_ID" ]]; then
    (( DRY_RUN )) || die "GOOGLE_OAUTH_CLIENT_ID is empty in .env (Google sign-in is the hosted gate); refusing to deploy"
    echo "# WARNING: GOOGLE_OAUTH_CLIENT_ID is empty in .env; the real run refuses to deploy" >&2
  fi
  SECRETS=(GOOGLE_API_KEY DSS_AGENT_TOKEN DSS_ACCESS_CODE)
fi
[[ "$OAUTH_CLIENT_ID$SIGNIN_ALLOW" != *"|"* ]] || die "GOOGLE_OAUTH_CLIENT_ID and DSS_SIGNIN_ALLOW may not contain '|'"

STATE_BUCKET="${PROJECT}-dss-state"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

# --- Guard (read-only, runs in --dry-run too): the right project and the existing service ---
number="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')" \
  || die "gcloud projects describe $PROJECT failed (expired credentials? run gcloud auth login)"
number="${number//$'\r'/}"  # gcloud on Windows ends lines with CRLF
[[ "$number" == "$EXPECTED_PROJECT_NUMBER" ]] \
  || die "project $PROJECT has number '$number', expected $EXPECTED_PROJECT_NUMBER; refusing"
url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region asia-southeast1 --format='value(status.url)')" \
  || die "gcloud run services describe $SERVICE failed"
url="${url//$'\r'/}"
if [[ "$url" != "$EXPECTED_URL" ]]; then
  # status.url can be the legacy <hash>.a.run.app form; the service also answers on every URL
  # in its run.googleapis.com/urls annotation (a JSON list), where the deterministic form lives.
  urls="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region asia-southeast1 \
    --format='value(metadata.annotations["run.googleapis.com/urls"])')" \
    || die "gcloud run services describe $SERVICE failed"
  [[ "$urls" == *"\"$EXPECTED_URL\""* ]] \
    || die "service $SERVICE does not serve $EXPECTED_URL (status.url '$url'); refusing"
  url="$EXPECTED_URL"
fi
BUILD_SA="${number}-compute@developer.gserviceaccount.com"

# --- Command helpers: print, then run unless --dry-run ---
show() {
  local out="+" a
  for a in "$@"; do
    if [[ "$a" =~ ^[A-Za-z0-9_./:=@,+%-]*$ ]]; then out+=" $a"; else out+=" '${a//\'/\'\\\'\'}'"; fi
  done
  printf '%s\n' "$out"
}
run() { show "$@"; (( DRY_RUN )) || "$@"; }
exists() { (( DRY_RUN )) && return 1; "$@" >/dev/null 2>&1; }

# A secret's value goes to gcloud on stdin; only its name is printed.
put_secret() {
  local name="$1" value
  value="$(env_get "$name")"
  if (( DRY_RUN )); then
    show gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic --data-file=-
    echo "  (if missing; value piped from .env $name. If it exists and differs:)"
    show gcloud secrets versions add "$name" --project "$PROJECT" --data-file=-
    return
  fi
  if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    local current
    current="$(gcloud secrets versions access latest --secret="$name" --project "$PROJECT" 2>/dev/null || true)"
    if [[ "$current" == "$value" ]]; then
      echo "  secret $name is current"
    else
      show gcloud secrets versions add "$name" --project "$PROJECT" --data-file=-
      printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- >/dev/null
    fi
  else
    show gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic --data-file=-
    printf '%s' "$value" | gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic --data-file=- >/dev/null
  fi
}

(( DRY_RUN )) && echo "# dry run: project $PROJECT ($number), region $REGION; nothing below runs"
if [[ -n "$PUBLIC" ]]; then echo "# mode: open link (DSS_PUBLIC=1, no sign-in, no code)"
else echo "# mode: gated (Google sign-in; access code for scripts)"; fi

echo "# APIs"
run gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com storage.googleapis.com bigquery.googleapis.com \
  --project "$PROJECT"

echo "# State bucket gs://$STATE_BUCKET (mounted at /data)"
if exists gcloud storage buckets describe "gs://$STATE_BUCKET" --project "$PROJECT"; then
  echo "  exists"
else
  run gcloud storage buckets create "gs://$STATE_BUCKET" --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access
fi

echo "# Runtime service account $RUNTIME_SA"
if exists gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT"; then
  echo "  exists"
else
  run gcloud iam service-accounts create "$RUNTIME_SA_NAME" --project "$PROJECT" \
    --display-name "dss-frontend runtime"
  # A new service account can take up to ~60 s to be visible to IAM bindings.
  if (( ! DRY_RUN )); then
    for _ in $(seq 1 12); do
      gcloud iam service-accounts describe "$RUNTIME_SA" --project "$PROJECT" >/dev/null 2>&1 && break
      sleep 5
    done
  fi
fi
for role in roles/bigquery.dataEditor roles/bigquery.jobUser; do
  run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$RUNTIME_SA" \
    --role "$role" --condition=None --quiet --format=none
done
run gcloud storage buckets add-iam-policy-binding "gs://$STATE_BUCKET" --project "$PROJECT" \
  --member "serviceAccount:$RUNTIME_SA" --role roles/storage.objectUser --format=none
if [[ -n "$GCS_BUCKET" ]]; then
  run gcloud storage buckets add-iam-policy-binding "gs://$GCS_BUCKET" --project "$PROJECT" \
    --member "serviceAccount:$RUNTIME_SA" --role roles/storage.objectViewer --format=none
fi

echo "# Build service account $BUILD_SA (source deploys)"
run gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$BUILD_SA" \
  --role roles/run.builder --condition=None --quiet --format=none

echo "# Secrets"
for name in "${SECRETS[@]}"; do
  put_secret "$name"
  run gcloud secrets add-iam-policy-binding "$name" --project "$PROJECT" \
    --member "serviceAccount:$RUNTIME_SA" --role roles/secretmanager.secretAccessor --format=none
done

# '|' delimits the env list (gcloud's ^|^ syntax): DSS_SIGNIN_ALLOW is itself a comma list.
ENV_VARS="^|^GCP_PROJECT_ID=$PROJECT|BQ_DATASET=$BQ_DATASET|BQ_LOCATION=$BQ_LOCATION"
ENV_VARS+="|DSS_DATA_DIR=/data|DSS_DB_PATH=/tmp/dss.sqlite|DSS_ENGINE_MODE=agent"
ENV_VARS+="|DSS_STATIC_DIR=/app/frontend/dist"
ENV_VARS+="|DSS_PUBLIC=$PUBLIC|GOOGLE_OAUTH_CLIENT_ID=$OAUTH_CLIENT_ID|DSS_SIGNIN_ALLOW=$SIGNIN_ALLOW"
[[ -n "$GCS_BUCKET" ]] && ENV_VARS+="|GCS_BUCKET=$GCS_BUCKET"
SECRET_REFS=""
for name in "${SECRETS[@]}"; do SECRET_REFS+="${SECRET_REFS:+,}$name=$name:latest"; done

echo "# Deploy (every setting in full: nothing of the previous revision carries over)"
run gcloud run deploy "$SERVICE" --source . --project "$PROJECT" --region "$REGION" --quiet \
  --build-service-account "projects/$PROJECT/serviceAccounts/$BUILD_SA" \
  --service-account "$RUNTIME_SA" --port 8080 --ingress all --allow-unauthenticated \
  --execution-environment gen2 --min-instances 0 --max-instances 1 --no-cpu-throttling \
  --cpu 2 --memory 2Gi --timeout 3600 \
  --command= --args= \
  --startup-probe "httpGet.path=/api/health,httpGet.port=8080,periodSeconds=10,timeoutSeconds=5,failureThreshold=30" \
  --clear-volumes --add-volume "name=state,type=cloud-storage,bucket=$STATE_BUCKET" \
  --clear-volume-mounts --add-volume-mount "volume=state,mount-path=/data" \
  --set-env-vars "$ENV_VARS" --set-secrets "$SECRET_REFS"

run gcloud run services update-traffic "$SERVICE" --project "$PROJECT" --region "$REGION" --to-latest

if (( DRY_RUN )); then
  echo "# dry run done; the service URL stays $url"
else
  gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)'
fi
