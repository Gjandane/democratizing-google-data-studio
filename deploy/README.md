# Deploy to Cloud Run

`deploy.sh` sets up the GCP resources (idempotent) and deploys the hosted app as Cloud Run service
`dss-frontend` in `asia-southeast1`: one image from the root `Dockerfile` (backend + built frontend
+ Playwright Chromium, no engine). Two modes, chosen by `DSS_PUBLIC` in `.env`
(contracts/conventions.md 1.6):
- `DSS_PUBLIC=1`, open link (the current choice): no sign-in and no code; anyone with the URL gets
  in. `GOOGLE_OAUTH_CLIENT_ID` and `DSS_SIGNIN_ALLOW` are deployed empty and the service gets no
  `DSS_ACCESS_CODE`.
- `DSS_PUBLIC` empty, gated: Google sign-in in the browser (the access code stays for scripts and
  the e2e drivers). Any other value refuses to deploy.

The hosted app goes through the staged workflow and prototype to the compiled recipe. Build issues
a one-time job code and shows one command to copy (contracts/conventions.md 1.7, Build agent): the
visitor runs it on their own machine (Chrome required; Windows tested, macOS/Linux untested), and
`agent-setup/setup.ps1` / `setup.sh` install the agent there and build the report into the
visitor's own Data Studio. The build's data reaches that report as one CSV in the share bucket
(below), so any Google account works.

The URL and the project number live only in the root `.env` (`DSS_AGENT_SERVER`,
`GCP_PROJECT_NUMBER`): the repo is public, the link is shared privately.

## Before you run it
- gcloud signed in with an account that owns the project: `gcloud auth login` (and
  `gcloud auth application-default login` for the local tools).
- The root `.env` holds `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `DSS_AGENT_SERVER` (the service
  URL), `GOOGLE_API_KEY` and `DSS_PUBLIC`; gated also
  `DSS_ACCESS_CODE` (at least 12) and `GOOGLE_OAUTH_CLIENT_ID`, optional `DSS_SIGNIN_ALLOW`. Optional
  in both: `GCP_REGION` (default `asia-southeast1`), `BQ_DATASET`, `BQ_LOCATION`, `GCS_BUCKET`. The
  script parses the file (never `source`s it) and refuses to run when a value is missing or too
  short (an empty `GOOGLE_OAUTH_CLIENT_ID` when gated only warns in `--dry-run`). It no longer
  reads the retired agent token (per-job codes replaced it); `DSS_SHARE_BUCKET` and
  `DSS_SHARE_DIR` are set by the script, not read from `.env`.
- Every run first checks that `GCP_PROJECT_ID` has the number `GCP_PROJECT_NUMBER` and that
  `dss-frontend` already serves `DSS_AGENT_SERVER`, in `--dry-run` too, and stops otherwise.
- Gated only: an OAuth client (Google Auth Platform > Clients > Web application) with Authorized JavaScript
  origins: the service URL, `http://localhost:5173` and `http://localhost:8000`; its id in `.env`
  as `GOOGLE_OAUTH_CLIENT_ID`. Consent screen External and In production (basic scopes need no
  verification; Testing admits only listed test users).
- bash 4+ (Git Bash, Linux, Cloud Shell).

## Run
```bash
bash deploy/deploy.sh --dry-run   # prints every gcloud command; secret values never appear
bash deploy/deploy.sh             # set up and deploy; prints the URL
```

What it creates (once) and sets (every run):

| Resource | Name |
|---|---|
| APIs | run, cloudbuild, artifactregistry, secretmanager, iam, storage, bigquery |
| State bucket, mounted at `/data` | `gs://<project>-dss-state` (SQLite backup, build files) |
| Share bucket, mounted at `/share` | `gs://<project>-dss-share` in `GCP_REGION`, uniform bucket-level access: each hosted run's view as `<hex>/data.csv`, readable by anyone who has its exact name, never listable |
| Custom role | `projects/<project>/roles/dssShareObjectGet`: only `storage.objects.get`, granted to `allUsers` on the share bucket (never `roles/storage.objectViewer`, which lists); each run resets its permissions to that one |
| Runtime service account | `dss-runtime@<project>.iam.gserviceaccount.com`: BigQuery Data Editor + Job User, Secret Accessor on the deployed secrets, Storage Object User on the state and share buckets, Storage Object Viewer on `GCS_BUCKET` when set |
| Build service account | `<number>-compute@developer.gserviceaccount.com`: `roles/run.builder` |
| Secrets | `GOOGLE_API_KEY`, and `DSS_ACCESS_CODE` only when gated (values piped from `.env`; a changed value adds a new version) |
| Service | `dss-frontend`: gen2, 0 to 1 instance (scales to zero), 2 vCPU / 2 GiB, CPU always on while up, timeout 3600 s, startup probe `/api/health`, env (incl. `DSS_PUBLIC`, `GOOGLE_OAUTH_CLIENT_ID`, `DSS_SIGNIN_ALLOW`, `DSS_SHARE_BUCKET`, `DSS_SHARE_DIR=/share`) and secrets replaced in full, then traffic to latest |

If an organization policy enforces public access prevention, granting `allUsers` fails and the
script stops: never work around it with a listable role.

Upload check (what Cloud Build receives, see `.gcloudignore`): `gcloud meta list-files-for-upload`.

Cost: one instance with 2 vCPU and 2 GiB that scales to zero: billed only while a request, an open
tab's event stream or a run keeps it up, about USD 0.13 per hour up; cold starts accepted. Plus
small Cloud Build, Artifact Registry, Secret Manager and storage charges (the share bucket's CSVs:
cents a month). Tear down below.

## Who gets in
Open link (`DSS_PUBLIC=1`): anyone with the URL, with no sign-in. Every visitor spends the owner's
Gemini key and BigQuery, sees and changes every build in the one shared history, and can change
the model settings (`PUT /api/settings`) for everyone; GCS and BigQuery sources are locked
(`403 source_locked`). Every Build writes that build's data as a CSV in the share bucket that
anyone with its name (it is in the recipe) can read; it stays until the link is closed. Set a
billing budget alert and a quota on the Gemini API key in the Console.

## Close the link after 2026-11-07
Nothing closes it automatically. Pick one:
- Gate it: in `.env` empty `DSS_PUBLIC`, set a `DSS_ACCESS_CODE` of at least 12 characters and a
  `GOOGLE_OAUTH_CLIENT_ID` from a project whose OAuth branding is External (see Before you run
  it), optionally `DSS_SIGNIN_ALLOW` (a comma list of `@<domain>` and exact emails, for example
  `DSS_SIGNIN_ALLOW=@example.com,judge@gmail.com`; empty admits any Google account), then
  `bash deploy/deploy.sh` (it adds the `DSS_ACCESS_CODE` secret and replaces env and secrets).
- Or take it offline: delete the service (first line of Tear down).

Either way, stop the published CSVs being readable (the visitors' Data Studio reports then lose
their data):
- Service deleted: delete the share bucket, `gcloud storage rm --recursive "gs://$PROJECT-dss-share"`.
- Gated: keep the bucket (the service mounts it at `/share`; deleting it breaks the next cold start)
  and empty it and drop the public grant instead. Every later `deploy.sh` run grants `allUsers`
  again, so repeat both after each gated deploy.

```bash
gcloud storage rm "gs://$PROJECT-dss-share/**"
gcloud storage buckets remove-iam-policy-binding "gs://$PROJECT-dss-share" --member allUsers --role "projects/$PROJECT/roles/dssShareObjectGet"
```

## Roll back to the static frontend
The revision that served the static frontend before the first deploy of the full app:
`dss-frontend-00001-s7w` (created 2026-10-18; read with
`gcloud run revisions list --service dss-frontend --region asia-southeast1`).

```bash
gcloud run services update-traffic dss-frontend --region asia-southeast1 --project "$PROJECT" --to-revisions dss-frontend-00001-s7w=100
```

A rollback pins traffic to that revision: later deploys create new revisions that get no traffic
until `--to-latest` undoes the pin (`deploy.sh` runs it at the end of every deploy):

```bash
gcloud run services update-traffic dss-frontend --region asia-southeast1 --project "$PROJECT" --to-latest
```

## Tear down
Run with `PROJECT=<GCP_PROJECT_ID>` and `NUMBER=<GCP_PROJECT_NUMBER>` (both from `.env`) set. Deleting the service takes the
URL offline (redeploying the same name in the same project and region brings the same URL back).

```bash
gcloud run services delete dss-frontend --region asia-southeast1 --project "$PROJECT"
gcloud secrets delete GOOGLE_API_KEY --project "$PROJECT"
gcloud secrets delete DSS_ACCESS_CODE --project "$PROJECT"   # only if it was ever deployed gated
gcloud secrets delete DSS_AGENT_TOKEN --project "$PROJECT"   # left over from deploys before 4.5, if present
gcloud storage rm --recursive "gs://$PROJECT-dss-state"
gcloud storage rm --recursive "gs://$PROJECT-dss-share"
gcloud iam roles delete dssShareObjectGet --project "$PROJECT"
gcloud projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:dss-runtime@$PROJECT.iam.gserviceaccount.com" --role roles/bigquery.dataEditor --condition=None
gcloud projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:dss-runtime@$PROJECT.iam.gserviceaccount.com" --role roles/bigquery.jobUser --condition=None
gcloud iam service-accounts delete "dss-runtime@$PROJECT.iam.gserviceaccount.com" --project "$PROJECT"
gcloud projects remove-iam-policy-binding "$PROJECT" --member "serviceAccount:$NUMBER-compute@developer.gserviceaccount.com" --role roles/run.builder --condition=None
gcloud artifacts repositories delete cloud-run-source-deploy --location asia-southeast1 --project "$PROJECT"
```
`gcloud storage rm` deletes the hosted history (the SQLite backup and every build's files) for
good. If `GCS_BUCKET` was set, also remove the runtime account's viewer binding on it
(`gcloud storage buckets remove-iam-policy-binding gs://<GCS_BUCKET> --member ... --role roles/storage.objectViewer`).
