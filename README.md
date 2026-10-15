# EcoLens — Greener packaging decisions, without the guesswork

**AWS CendekiAwan 2.0 · Sustainable Environment & Climate**

## 📌 Summary

**EcoLens helps Malaysian food SMEs pick greener packaging they can afford, from
one photo, without hiring a packaging consultant.**

A seller snaps a photo of their current pack and adds a few details (budget,
product, sales channel). In about a minute EcoLens returns three costed redesign
options, a packaging audit with every claim labelled by how sure it is, the
option that best fits their constraints, and a brief they can send straight to
their supplier. It runs fully serverless on AWS in the Malaysia region
(`ap-southeast-5`), using Amazon Bedrock (Claude Haiku 4.5 for text, vision and
chat; Nova Canvas for redesign images).

## 🔗 Links

| What | Link |
|------|------|
| 🌐 Live app  | xxx|
| 📊 Pitch deck| [`pitch/EcoLens-Pitch-Canva.pdf`](pitch/EcoLens-Pitch-Canva.pdf) |
| Demo video | xxx |


## ❗ Problem Statement

### Meet our user

**Encik Syaful, 44 — home baker in Kajang.** He sells *biskut raya* in clear
plastic jars through WhatsApp, Shopee and corporate hampers. He packs about
**2,000 jars in the four weeks before Hari Raya**, and that one season pays for
most of his family's year. *(Representative persona based on reported Malaysian
sellers.)*

### The problem

A corporate client asks for **plastic-free hampers**. Every option he finds
fails him:

| Barrier | What it looks like for him |
|---------|----------------------------|
| 💸 **Costs more than he can absorb** | Kraft tube RM1.90 vs RM0.85 jar → **+RM2,100** across one Raya season |
| 📦 **Doesn't protect the product** | Kuih bangkit go soft in our humidity; paper tubes get crushed by couriers |
| ❓ **He can't tell which claim is real** | "Biodegradable" jars that nobody in Kajang collects — they'd go to landfill anyway |
| ⏳ **No expert, no time** | A consultant costs more than his margin, minimum orders are 5,000 units, and Ramadan is his busiest month |

**Result:** he keeps the plastic and loses the hamper order.

### It's not just him

- *The Star, 30 Jun 2025* — a kuih chang seller in Ampang stays with plastic
  because paper wraps don't survive parcel handling.
- *Bernama, 9 Sep 2025* — food and beverage packaging is "often considered too
  expensive or too hard to be recycled".
- **1.09 million MSMEs** make up **96.1%** of Malaysian businesses (DOSM 2024),
  and **EPR packaging rules become mandatory by 2030**.

### How it's solved today

|                        | Affordable | Knows his product | Malaysian recycling | Same day |
|------------------------|------------|-------------------|---------------------|----------|
| Packaging consultant   | ❌ No       | ✅ Yes             | ✅ Yes               | ❌ Weeks  |
| Supplier's advice      | ✅ Free     | ⚠️ Partly          | ⚠️ Biased to stock   | ✅ Yes    |
| Online guides          | ✅ Free     | ❌ Generic         | ❌ Western systems   | ✅ Yes    |
| **EcoLens**            | ✅ **RM29 / month** | ✅ **From his photo** | ✅ **Built in** | ✅ **~1 minute** |

## 💡 Solution

**One photo in. A supplier-ready decision out.**

1. **Snap the pack** — a photo plus a few details, in English or BM.
2. **Three options** — Quick Win, Balanced and Ambitious, each with cost,
   difficulty and risk.
3. **Checked evidence** — every finding labelled **Observed**, **Inferred**,
   **Verified** or **Unknown**.
4. **Best fit and brief** — the option that fits his constraints, plus a brief
   to send his supplier.

### Why it needs AI

A form or a search engine can't do these four things:

| Capability | What it does for the seller |
|------------|-----------------------------|
| **Vision** — reads packaging from a photo | Sees a clear jar, a coloured lid, a tray and no resin code, so he doesn't need to know material names |
| **Reasoning** — weighs trade-offs for *his* product | Balances RM budget, shelf life in Malaysian humidity, courier damage and hand-filling together |
| **Unstructured input** — turns uncertainty into labels | Separates what it can see from what it is guessing, so he knows what to ask his supplier |
| **Language** — speaks his language | Understands English, Bahasa Malaysia and Manglish, and answers follow-up questions about his own report |

## ✨ Features

- **Three redesign strategies** (Quick Win / Balanced / Ambitious) with cost,
  difficulty and risk
- **Packaging audit** with every finding labelled Observed / Inferred / Verified / Unknown
- **Prioritised list of sustainability problems**
- **Best-fit recommendation + supplier-ready brief**
- **Side-by-side trade-off comparison** — cost, protection, shelf-life risk and
  recyclability in Malaysia
- **Three AI-generated redesign visuals** (Option A / B / C)
- **Knowledge-aware chatbot** that answers in English or Bahasa Malaysia, with
  the whole report as context
- **Photo auto-detect** — reads product name, materials and category from the
  image to pre-fill the form (everything stays editable)
- **Wrong-input guard** — a photo that isn't packaging gets "Wrong input
  detected" instead of an invented answer
- **Try an example** — one click loads a sample cookie-jar run with ready-made visuals
- **Downloadable PDFs** — a designed full report and a one-page supplier brief
- **Live camera capture**, EN/BM toggle and light/dark theme
- **Localised for Malaysia** — understands English / BM / Manglish, defaults to
  RM and grams/gsm, and reflects local recycling, halal and climate realities
- **Privacy by design** — no database; nothing about the user is stored

### Example result — Encik Syaful's biskut raya jars

> **Best fit: keep the jar, fix the material.** EcoLens picked **Option B**, a
> single-material PP jar: cookies stay crisp, it's hand-fillable, it's actually
> collected and sorted in the Klang Valley, and it stays within his **RM0.30 per
> jar** limit. ✅ Within budget · ✅ No new machine · ✅ Recyclable in Malaysia
>
> Where it can't tell, it says so — the jar material is marked **"Unknown,
> requires verification"** rather than guessed.

## 🏗️ Architecture

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
## 🌍 Impact

### Who benefits

Home-based and small **food & beverage sellers** who need greener packaging for
customers, marketplaces and upcoming EPR rules, but can't afford a consultant or
a wrong choice. One avoided wrong decision can save a seller like Encik Syaful
around **RM2,100 in a single season**.

Supports **SDG 9** (Industry, Innovation & Infrastructure), **SDG 12**
(Responsible Consumption & Production) and **SDG 13** (Climate Action).

### Market size

| | Annual value | Businesses | Basis |
|---|---|---|---|
| **TAM** | RM67.5M | 193,895 | Manufacturing MSMEs (57,187) + F&B businesses (136,708) × RM348/year |
| **SAM** | RM50.6M | 145,286 | Food & beverage businesses — the users our halal, shelf-life and humidity checks are built for |
| **SOM** | RM0.51M | 1,453 | 1% of SAM by year 3, through one pilot partner and SME agencies |

*Sources: DOSM MSME 2024 (via OECD); DOSM Economic Census 2023. Price RM29/month.*

### Business model

| | |
|---|---|
| **Price** | RM29 / month, unlimited reports — first 3 reports free |
| **AWS cost per report** | ≈ RM0.40 (6 Claude Haiku calls + 1 image, estimate) |
| **Gross margin** | ≈ 94% at 4 reports a month per subscriber |

### Scaling — what breaks first at 100,000 users

- **Bedrock rate limits on Claude Haiku** → request a quota increase and queue bursts
- **Image service quotas** → move fully to Nova Canvas in `us-east-1`
- **30-second API Gateway limit** → switch long sections to true streaming

### Who gets left out, and our plan

- **Low digital literacy** → BM by default, photo-first flow, brief sent by WhatsApp
- **No smartphone or data** → run sessions through SME agencies and co-ops
- **Not a certification** → EcoLens tells users what to verify with suppliers

## 🚀 Pilot & Roadmap

**Pilot:** SME Corp Malaysia's food entrepreneurs, **February 2027**, ahead of the
Raya 2027 rush.

- 50 home-based food sellers
- **Measure:** switches made, cost per pack, supplier briefs sent
- **Success:** 1 in 3 sellers changes at least one packaging part

**If we had 3 more weeks:**

- **Photo-only flow** — no form, one best-fit answer first (already built on a branch)
- **Stronger images** — Nova Canvas for every redesign visual
- **Local supplier directory** — so the brief goes to a real Malaysian supplier

**Our ask:**

- **A pilot partner** — an SME agency or food co-op to put EcoLens in front of
  50 sellers before Raya 2027
- **AWS credits** — to run the pilot 

**Why we win:** built for Malaysia — our recycling reality, halal, humidity, BM
and costs in RM. Big platforms won't build for a 2,000-jar baker.

> *Encik Syaful shouldn't have to choose between his income and the planet.
> EcoLens shows him the option that protects both.*

---

<div align="center">
  <strong>Made by Team 3 - Wo dou Bu Zhi Dao</strong>
  <br>
  <strong><em>© AWS CendekiAwan 2.0</em></strong>
</div>





