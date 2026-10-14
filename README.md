# 🌱 EcoLens — Sustainable Packaging Decision

A deployable AWS web app that helps Malaysian SMEs make greener packaging
decisions without guessing on cost, shelf life or product protection. Upload a
photo of your packaging and a few business details, and EcoLens produces:

- **Three redesign strategies** (Quick Win / Balanced / Ambitious)
- A **packaging audit** with every finding labelled Observed / Inferred / Verified / Unknown
- A **prioritised list of sustainability problems**
- A **best-fit recommendation + supplier-ready brief**
- A **side-by-side trade-off comparison**
- **Three AI-generated redesign visuals** (Option A / B / C)
- A **knowledge-aware chatbot** that answers in English or Bahasa Malaysia

Localised for Malaysian SMEs: understands English / BM / Manglish, defaults to
RM and grams/gsm, and reflects realistic local recycling, halal and climate
considerations.

Supports **SDG 9** (Industry & innovation), **SDG 12** (Responsible
Consumption & Production) and **SDG 13** (Climate Action).

---

## Architecture

```
Browser
  │  (HTTPS via CloudFront → S3 static website origin)
  │
  ├── POST → API Gateway HTTP API ($default) → 6 Flask Lambdas (text/chat)
  │                                             via Lambda Web Adapter
  │                                             → Amazon Bedrock
  │                                               (Claude Haiku 4.5, global profile)
  │
  └── POST → API Gateway REST API (prod)      → Image Lambda (standard handler)
                                                → image provider chain → base64 PNG
```

**Image provider chain (first that succeeds wins):**
1. Amazon Bedrock **Nova Canvas** (`amazon.nova-canvas-v1:0`) in **us-east-1**
2. Amazon Bedrock **Titan Image Generator v2** (`amazon.titan-image-generator-v2:0`) — fallback for accounts where Nova is blocked
3. **Google Gemini** image model — only if `GeminiApiKey` is provided
4. **Hugging Face FLUX** — only if `HfToken` is provided
5. **Pollinations** (`image.pollinations.ai`, FLUX) — a free, key-less last resort so an image is always returned even if every provider above fails. Note: this calls an external third-party service with no key; remove this tier from `backend/image-generator/app.py` if that is not acceptable for your use.

> Nova Canvas is **not** available in `ap-southeast-5`, so the image Lambda is
> pinned to `us-east-1` via the `BEDROCK_REGION` environment variable. The text
> Lambdas use the **global** Claude Haiku 4.5 inference profile, which is
> invocable from `ap-southeast-5`.

| Layer      | Service                                                        |
|------------|----------------------------------------------------------------|
| Frontend   | Single `index.html` on S3 static website hosting, served over HTTPS by CloudFront |
| Text/Chat  | 6 × AWS Lambda (Python 3.12, Flask + Lambda Web Adapter)       |
| Image      | 1 × AWS Lambda (Python 3.12, standard handler, multi-provider)|
| AI         | Amazon Bedrock (Claude Haiku 4.5 text; Nova Canvas / Titan image) + optional Gemini / Hugging Face |
| Infra      | AWS SAM (`infra/template.yaml`)                                |
| CI/CD      | GitHub Actions (`.github/workflows/deploy.yml`)                |

### Project layout

```
backend/
  three-redesign-strategies/        app.py  run.sh  requirements.txt
  sustainability-problems-identified/
  packaging-audit-and-evidence-classification/
  best-fit-recommendation-and-supplier-brief/
  trade-off-comparison/
  ecolens-chatai/
  image-generator/                  app.py  requirements.txt   (serves Option A/B/C)
frontend/
  index.html                        landing page + analyser, themes, i18n, streaming UI
infra/
  template.yaml                     SAM template
pitch/
  EcoLens-Pitch-Canva.pdf           pitch deck + slide PNGs + HTML version
.github/workflows/
  deploy.yml                        bucket + build + deploy + URL injection + S3 sync + CDN invalidation
```

---

## ✅ Pre-deployment checklist

### 1. Enable Bedrock model access (one-time)

In the AWS Console → **Bedrock → Model access**:

- In **`ap-southeast-5` (Malaysia)**: enable **Claude Haiku 4.5**
  (`global.anthropic.claude-haiku-4-5-20251001-v1:0`, the global cross-region
  inference profile — this is why the IAM policy uses `*` for region on the
  foundation-model ARNs).
- In **`us-east-1`**: enable **Nova Canvas** (`amazon.nova-canvas-v1:0`) and,
  as a fallback, **Titan Image Generator v2** (`amazon.titan-image-generator-v2:0`).
  Model access is per-region, and the image Lambda calls `us-east-1`.

First-time accounts must submit the Anthropic use-case form before access is granted.

### 2. Add GitHub repository secrets

| Secret                  | Required | Value                                         |
|-------------------------|----------|-----------------------------------------------|
| `AWS_ACCESS_KEY_ID`     | yes      | IAM user/role access key                      |
| `AWS_SECRET_ACCESS_KEY` | yes      | matching secret key                           |
| `GEMINI_API_KEY`        | optional | Google Gemini key — only for the Gemini image fallback |
| `HF_TOKEN`              | optional | Hugging Face token — only for the FLUX image fallback |

The optional keys can be left unset; the image Lambda just uses the Bedrock
providers in that case.

### 3. IAM permissions for the deploy principal

The deploying IAM user/role needs permissions for CloudFormation, Lambda, IAM
(named role creation — hence `CAPABILITY_NAMED_IAM`), API Gateway, S3 (including
creating the deploy bucket), and **CloudFront** (`CreateDistribution`,
`UpdateDistribution`, `CreateInvalidation`, `GetDistribution`, tagging). Missing
CloudFront rights is the most common first-deploy failure.

---

## 🚀 Deploy

Push to `main` (or run the **Deploy EcoLens** workflow manually). The workflow:

1. Checks out the repo and configures AWS credentials.
2. `sam build --template infra/template.yaml`.
3. Ensures a deterministic deploy bucket exists in `ap-southeast-5`
   (`ecolens-sam-deploy-ap-southeast-5-<account-id>`), creating it in-region if
   needed — this avoids the S3 "location constraint" region-mismatch error.
4. `sam deploy` to the `ecolens` stack in `ap-southeast-5`, passing the optional
   `GeminiApiKey` / `HfToken` parameter overrides.
5. Reads the CloudFormation outputs and `sed`-injects each endpoint URL into
   `frontend/index.html` (replacing the `__URL_*__` / `__DIAGRAM_API_URL__`
   placeholders).
6. `aws s3 sync` the frontend to the website bucket (`--cache-control no-cache`).
7. Invalidates the CloudFront cache so the new frontend is served immediately.
8. Prints both the S3 (HTTP) and the **CloudFront HTTPS** URLs.

> No `samconfig.toml` is committed (it can cause version-key errors in CI). All
> deploy parameters are passed as flags.

> **First deploy is slow** — creating the CloudFront distribution typically takes
> 5–15 minutes. Later deploys are fast.

### Which URL to use

Open the **`HttpsWebsiteUrl`** output (`https://<id>.cloudfront.net`). HTTPS is
required for the in-page **live camera** (`getUserMedia` needs a secure context);
on the plain HTTP S3 URL the camera button falls back to the device file/camera
picker.

---

## Key behaviours

- **Streaming text UI** — text/chat widgets are fetched with
  `fetch()` + `response.body.getReader()`, decoded with `TextDecoder`, buffered by
  line, and rendered as fade-in markdown spans with a blinking cursor (a typing
  effect; the HTTP API returns the whole answer at once).
- **File upload** — the dropzone reads the file with `FileReader.readAsDataURL()`,
  strips the `data:<mime>;base64,` prefix, and sends `file_data` + `file_mime` in
  the POST body. There is also a live-camera capture modal.
- **Image widgets** POST `{ option, fields, strategies }` to the REST API and
  render the returned base64 PNG.
- **Chat** sends the full `history` plus a `context` object with every analysis
  output, so it answers with knowledge of the whole report. **Reset** clears
  inputs/outputs but keeps the chat memory.
- **Language & theme** — EN/BM toggle and light/dark theme, both persisted in
  `localStorage`.
- **Resilient errors** — if a text Lambda can't reach the model, it logs the full
  traceback to CloudWatch and returns a readable `⚠️ ...` message (HTTP 200)
  instead of a bare 500, so the on-screen panel shows the real reason.

---

## Local / operational notes

- Each text Lambda is a standalone Flask app; `run.sh` (`python app.py`) is the
  entrypoint, started by the Lambda Web Adapter layer. A `GET /` health route
  returns 200 for the adapter readiness check.
- **Timeouts**: text functions are 29s (the HTTP API hard-limits requests at 30s);
  generation stops at ~24s and returns what it has, noting it was shortened. The
  image function allows longer.
- `sam validate` is not run locally during authoring; the GitHub Actions
  `sam build` step is the first full validation.

### Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| Text panel shows `⚠️ ... AccessDeniedException` | Claude Haiku 4.5 model access not enabled in `ap-southeast-5` |
| Image panels fail | Nova Canvas / Titan not enabled in `us-east-1` (or set `GEMINI_API_KEY` / `HF_TOKEN`) |
| Deploy fails on `FrontendDistribution` | Deploy principal lacks CloudFront permissions |
| Deploy fails with S3 "location constraint" | Deploy bucket is in the wrong region (the workflow now creates it in-region) |
| Camera opens a file picker instead of live preview | You are on the HTTP S3 URL — use the CloudFront HTTPS URL |
