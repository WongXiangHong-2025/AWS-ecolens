# 🌱 EcoLens — Sustainable Packaging Decision

A deployable AWS version of the EcoLens PartyRock app. It analyses a packaging
image together with business requirements and produces practical redesign
strategies, a packaging audit, a sustainability problem list, a best-fit
supplier brief, a trade-off comparison, three AI-generated redesign visuals,
and a knowledge-aware chatbot.

Supports **SDG 9** (Industry, innovation and infrastructure),
**SDG 12** (Responsible Consumption and Production), and **SDG 13** (Climate Action).

---

## 🎯 Problem Statement

Small and medium enterprises (SMEs) in Malaysia and Southeast Asia want to switch
to more sustainable packaging, but they lack the expertise, time and budget to
make that decision with confidence. Today, an SME owner typically faces:

- **No in-house packaging expertise.** Large brands have packaging engineers and
  sustainability teams. Most SMEs have one person doing everything, and
  packaging consultants are expensive.
- **Fear of hidden risks.** A "greener" material can raise unit cost, shorten
  shelf life, fail to protect the product in a hot and humid climate, or need
  new packing machinery. These risks stop many SMEs from changing anything.
- **Generic, unrealistic advice.** Most sustainability guidance is written for
  Western markets. It ignores Malaysian recycling realities (limited kerbside
  and soft-plastic recycling that varies by council), halal and food-contact
  requirements, and costs in Ringgit.
- **Unverified green claims.** It is hard to tell what is actually known about
  your packaging and what is only assumed, which risks greenwashing, especially
  for exports to markets such as the EU with stricter packaging rules.
- **Hard to act on.** Even with a good idea, SMEs struggle to turn it into a
  clear specification a supplier can quote and test against.

**As a result, much SME packaging stays over-packaged, hard to recycle and
reliant on virgin plastic. The cause isn't unwillingness; there's no practical,
affordable way to decide what to change.**

## 🌍 Problem Fit

EcoLens targets the packaging decisions of **Malaysian and Southeast Asian SMEs**,
especially in food and beverage, personal care and other consumer goods. It maps
to three UN Sustainable Development Goals:

| SDG | How EcoLens contributes |
|-----|-------------------------|
| **SDG 9** — Industry, innovation and infrastructure | Gives small manufacturers access to AI-powered packaging analysis that was previously only affordable for large companies, helping them upgrade their packaging sustainably. |
| **SDG 12** — Responsible consumption and production (Target 12.5: reduce waste through prevention, reduction, recycling and reuse) | Recommends material reduction, lightweighting, mono-material, recycled-content and reuse/refill options. Every claim is labelled with its evidence level to discourage greenwashing. |
| **SDG 13** — Climate action | Less material and more recyclable packaging lowers the carbon footprint of production, transport and end-of-life. |

## 💡 Our Solution

EcoLens is an AI packaging advisor that turns **one photo and a few answers**
into a decision-ready report in under a minute. The SME uploads a photo (or PDF)
of its current packaging and states the product, category and sustainability
goal, plus optional details such as shelf life, cost limits, machinery and target
market. EcoLens then produces:

| Output | What it solves |
|--------|----------------|
| **Three redesign strategies** — A: Quick Win, B: Balanced, C: Ambitious | Realistic choices at different levels of cost, effort and risk, instead of one "ideal" answer. Flags any **constraint conflict** with the stated budget, machinery or shelf life. |
| **Packaging audit and evidence classification** | Lists every visible packaging element and labels each finding **Observed / Inferred / Verified / Unknown**, so the SME knows exactly what to double-check before making a claim. |
| **Sustainability problems identified** | Ranks issues as High / Medium / Low priority and explains why each matters for this product. |
| **Trade-off comparison** | Compares current packaging with each option on cost, protection, shelf life, recyclability and more, side by side. |
| **Best-fit recommendation and supplier brief** | Picks the option that best fits the business (not automatically the greenest) and writes a **supplier-ready brief**: specs, tests, certificates and evidence to request. |
| **Redesign visuals (Option A/B/C)** | Photorealistic previews of each redesign, keeping the original branding, so the owner can see the change before committing. |
| **EcoLens ChatAI** | A follow-up advisor that has read the whole report and remembers the conversation. |

### What makes it fit SMEs

- **Local context built in.** Costs in RM. Reflects Malaysian recycling
  infrastructure. Considers halal integrity, food-contact safety and tropical
  heat and humidity. Notes export obligations at a high level.
- **Bilingual.** Understands and replies in English, Bahasa Malaysia or a mix.
- **Business first, not green at any cost.** Recommendations respect stated
  constraints and are written like a packaging consultant's advice, not a
  generic checklist.
- **Honest about uncertainty.** It never invents specifications, certifications
  or recycled-content percentages. Input that isn't real packaging is rejected
  ("Wrong input detected") instead of producing a made-up analysis.
- **Free to use, no sign-up.** It's a static website backed by serverless AWS,
  so the cost per analysis stays low.

### How it is built

The text analyses and chat run on **Claude Haiku 4.5 via Amazon Bedrock**.
Redesign visuals use **Amazon Nova Canvas**, falling back automatically to
Titan Image Generator v2, then Gemini 2.5 Flash Image (if a key is configured),
then Pollinations.ai, so a visual is still produced when one provider is
unavailable. Everything is serverless on AWS Lambda in `ap-southeast-5`
(Malaysia). See [Architecture](#architecture) below.

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
                                                   → Bedrock Nova Canvas → Titan v2 → Gemini → Pollinations
                                                     (first that succeeds) → base64 image
```

| Layer      | Service                                                        |
|------------|----------------------------------------------------------------|
| Frontend   | Single `index.html` on S3 static website hosting               |
| Text/Chat  | 6 × AWS Lambda (Python 3.12, Flask + Lambda Web Adapter)        |
| Image      | 1 × AWS Lambda (Python 3.12, standard handler)                 |
| AI         | Amazon Bedrock — `global.anthropic.claude-haiku-4-5-20251001-v1:0` (text) and `amazon.nova-canvas-v1:0` (image, with Titan Image Generator v2 / Gemini / Pollinations.ai fallbacks) |
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
  index.html                        upload → best-fit result → supplier brief, EN/BM, themes
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

### 2. Add GitHub repository secrets

| Secret                   | Value                                         |
|--------------------------|-----------------------------------------------|
| `AWS_ACCESS_KEY_ID`      | IAM user/role access key                      |
| `AWS_SECRET_ACCESS_KEY`  | matching secret key                           |
| `GEMINI_API_KEY`         | *(optional)* Google Gemini key for the image fallback |

> No deploy bucket secret is needed. The workflow uses `sam deploy --resolve-s3`,
> which creates and reuses a SAM-managed artifacts bucket in `ap-southeast-5`
> automatically. This also avoids S3 region-mismatch errors.

The deploying principal needs permissions for CloudFormation, Lambda, IAM
(role creation — the role is named, hence `CAPABILITY_NAMED_IAM`), API Gateway,
and S3 (including creating the SAM managed bucket).

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
- `Timeout` is 29s for text functions (the HTTP API hard-limits requests at 30s;
  generation stops at ~24s and returns what it has, noting it was shortened)
  and 30s for the image function.
- `sam validate` was **not** run locally during authoring (no SAM CLI in the
  build environment); the GitHub Actions `sam build` step is the first full
  validation. If `sam build` reports an issue, fix `infra/template.yaml` and push
  again.
