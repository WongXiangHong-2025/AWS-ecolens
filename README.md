# 🌱 EcoLens — Sustainable Packaging Decision

A deployable AWS version of the EcoLens PartyRock app. It analyses a packaging
image together with business requirements and produces practical redesign
strategies, a packaging audit, a sustainability problem list, a best-fit
supplier brief, a trade-off comparison, three AI-generated redesign visuals,
and a knowledge-aware chatbot.

Supports **SDG 9** (Industry, innovation and infrastructure),
**SDG 12** (Responsible Consumption and Production), and **SDG 13** (Climate Action).

---

## Architecture

```
Browser (S3 static site)
   │
   ├── POST  → API Gateway HTTP API ($default)  → 6 Flask Lambdas (streaming text/chat)
   │                                               via Lambda Web Adapter
   │                                               → Amazon Bedrock (Claude Haiku 4.5, global profile)
   │
   └── POST  → API Gateway REST API (prod)       → Image Lambda (standard handler, buffered)
                                                   → Amazon Bedrock (Nova Canvas) → base64 PNG
```

| Layer      | Service                                                        |
|------------|----------------------------------------------------------------|
| Frontend   | Single `index.html` on S3 static website hosting               |
| Text/Chat  | 6 × AWS Lambda (Python 3.12, Flask + Lambda Web Adapter)        |
| Image      | 1 × AWS Lambda (Python 3.12, standard handler)                 |
| AI         | Amazon Bedrock — `global.anthropic.claude-haiku-4-5-20251001-v1:0` (text) and `amazon.nova-canvas-v1:0` (image) |
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
  index.html                        all 27 widgets, themes, streaming UI
infra/
  template.yaml                     SAM template
.github/workflows/
  deploy.yml                        build + deploy + URL injection + S3 sync
```

---

## ✅ Pre-deployment checklist

### 1. Enable Bedrock model access (one-time, in `ap-southeast-5` Malaysia)

In the AWS Console → **Bedrock → Model access**, request/enable:

- `global.anthropic.claude-haiku-4-5-20251001-v1:0` — the **global cross-region
  inference profile** (routes worldwide for throughput; this is why the IAM
  policy uses `*` for the region on the foundation-model ARNs).
- `amazon.nova-canvas-v1:0` — **Nova Canvas**, for image generation.

First-time accounts must submit the Anthropic use-case form before access is granted.

### 2. Create an S3 bucket for SAM deployment artifacts

```bash
aws s3 mb s3://your-sam-deploy-bucket --region ap-southeast-5
```

### 3. Add GitHub repository secrets

| Secret                   | Value                                         |
|--------------------------|-----------------------------------------------|
| `AWS_ACCESS_KEY_ID`      | IAM user/role access key                      |
| `AWS_SECRET_ACCESS_KEY`  | matching secret key                           |
| `SAM_DEPLOY_BUCKET`      | the bucket name from step 2                   |

The deploying principal needs permissions for CloudFormation, Lambda, IAM
(role creation — the role is named, hence `CAPABILITY_NAMED_IAM`), API Gateway,
and S3.

---

## 🚀 Deploy

Push to `main` (or run the **Deploy EcoLens** workflow manually). The workflow:

1. Checks out the repo and configures AWS credentials.
2. `sam build --template infra/template.yaml`.
3. `sam deploy` to the `ecolens` stack in `ap-southeast-5`.
4. Reads the CloudFormation outputs and `sed`-injects each endpoint URL into
   `frontend/index.html` (replacing the `__URL_*__` / `__DIAGRAM_API_URL__`
   placeholders).
5. `aws s3 sync` the frontend to the website bucket.
6. Prints the **WebsiteUrl**.

> No `samconfig.toml` is used (it can cause version-key errors in CI). All deploy
> parameters are passed as flags.

---

## How the frontend talks to the backend

- **Text / chat widgets** are fetched from the HTTP API with
  `fetch()` + `response.body.getReader()`. Chunks are decoded with `TextDecoder`,
  buffered by line, and each complete line is rendered as a fade-in markdown span
  with a blinking cursor on the active line (typing effect — the HTTP API returns
  the whole answer at once, so there is no true token streaming).
- **File upload**: the dropzone reads the file with `FileReader.readAsDataURL()`,
  strips the `data:<mime>;base64,` prefix, and sends `file_data` (raw base64) +
  `file_mime` in the POST body. Optional uploads are omitted when no file is set.
- **Image widgets** POST `{ option, fields, strategies }` to the REST API and
  render the returned base64 PNG.
- **Chat** sends the full `history` plus a `context` object containing every
  analysis output, so the assistant answers with knowledge of the whole report.
  The **Reset** button clears inputs and outputs but deliberately **keeps the chat
  memory**, as requested.
- **Theme**: light/dark toggle, persisted in `localStorage`.

---

## Local notes

- Each text Lambda is a standalone Flask app; `run.sh` (`python app.py`) is the
  Lambda handler, started by the Lambda Web Adapter layer. A `GET /` health route
  returns 200 for the adapter readiness check.
- `Timeout` is 25s for text functions (the HTTP API hard-limits requests at 30s)
  and 30s for the image function.
- `sam validate` was **not** run locally during authoring (no SAM CLI in the
  build environment); the GitHub Actions `sam build` step is the first full
  validation. If `sam build` reports an issue, fix `infra/template.yaml` and push
  again.
