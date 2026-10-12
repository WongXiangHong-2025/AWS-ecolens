"""
EcoLens — Packaging Redesign Visual (image generation widget).

Standard Lambda handler (no Flask). Serves Options A, B and C: the frontend
POSTs {"option": "A"|"B"|"C", "fields": {...}, "strategies": "<text>"} and
receives {"image_base64": "..."} back.

Tries Bedrock's amazon.nova-canvas-v1:0 via invoke_model first. If that call
fails (quota, access, region, etc.) and GEMINI_API_KEY is set, falls back to
Gemini's Nano Banana Pro image model. Either way the handler returns the
base64 PNG as JSON.
"""
import base64
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-5"))
# Bedrock image models tried in order, with each one's prompt length limit.
# Titan Image Generator v2 takes the same request format as Nova Canvas and is
# the fallback for accounts (e.g. hackathon sandboxes) where Nova is blocked.
IMAGE_MODELS = [
    ("amazon.nova-canvas-v1:0", 1024),
    ("amazon.titan-image-generator-v2:0", 512),
]

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_IMAGE_MODEL = os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
)

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}

COMMON_RULES = """

--- STRICT RULES ---

2. BRANDING: Strictly follow the branding requirements stated above. Preserve all brand colours, logo placement, typography style, and overall visual identity. Do not alter or remove any brand elements.

5. PHOTO STYLE: Photorealistic commercial product photograph. Studio lighting, clean neutral background, realistic material textures, professional retail quality. Same camera angle and perspective as a standard retail shelf product shot.

6. SHOW ONLY: The closed sealed finished external packaging. No open packaging, no exposed product contents, no hands, no people, no diagrams, no comparison graphics, no text callouts outside the package."""

OPTION_RULES = {
    "A": (
        "You are generating a photorealistic commercial product photograph of a SUBTLY "
        "REDESIGNED version of an existing product package.",
        """
1. PACKAGING FORMAT: Keep the EXACT same packaging format and structure as the current packaging described above — same shape, same format type (flow-wrap pouch, stand-up pouch, folding carton box, bottle, tray, sachet). Do NOT change the packaging format or structure.

3. MACHINERY: Respect the packaging machinery constraints stated above. Do not propose a packaging format that would require new machinery.

4. CHANGES: Apply ONLY the subtle Option A Quick Win changes described in the redesign strategy — slightly reduced dimensions, thinner material, added recycling symbol, or minor structural simplification. Changes must be minimal and barely noticeable."""
        + COMMON_RULES
        + "\n\nThe result must be immediately recognisable as the same product and brand, with only a very subtle sustainable improvement visible.",
    ),
    "B": (
        "You are generating a photorealistic commercial product photograph of a MODERATELY "
        "REDESIGNED version of an existing product package.",
        """
1. PACKAGING FORMAT: Keep the EXACT same packaging format and structure as the current packaging unless Option B explicitly states a format change.

3. MACHINERY: Respect the packaging machinery constraints stated above unless Option B explicitly allows a change.

4. CHANGES: Apply the Option B Balanced Redesign changes — material substitution, improved recyclability markings, modest structural changes, or recycled content integration. Changes should be noticeable but not radical."""
        + COMMON_RULES
        + "\n\nThe result must be recognisable as the same product and brand, with a clear but practical sustainable improvement visible.",
    ),
    "C": (
        "You are generating a photorealistic commercial product photograph of an AMBITIOUSLY "
        "REDESIGNED version of an existing product package.",
        """
1. PACKAGING FORMAT: Apply the significant format or material transformation described in Option C — mono-material structure, paper-based format, reusable packaging, or alternative structure. If Option C does not specify a new format, keep the original format but apply a major material change.

3. MACHINERY: Note any machinery changes implied by Option C. The packaging should look commercially manufacturable even if it represents a future investment.

4. CHANGES: Apply the bold Option C Ambitious Redesign changes — significant material transformation, new structure, or alternative format. Forward-looking and aspirational but still commercially plausible and retail-ready. Use natural sustainable material aesthetics (kraft paper, matte film, recycled board) where relevant."""
        + COMMON_RULES
        + "\n\nThe result should feel like a bold but real next-generation version of the same brand and product.",
    ),
}


def build_prompt(option, fields, strategies):
    header, rules = OPTION_RULES.get(option.upper(), OPTION_RULES["A"])
    f = fields or {}
    context = (
        f"\n\nProduct: {f.get('Product Name and Type', '')}"
        f"\nProduct category: {f.get('Product Category', '')}"
        f"\nCurrent packaging materials: {f.get('Current Packaging Materials', '')}"
        f"\nBranding requirements: {f.get('Branding Requirements', '')}"
        f"\nPackaging machinery constraints: {f.get('Packaging Machinery Constraints', '')}"
    )
    strategy_block = ""
    if strategies:
        strategy_block = f"\n\nRedesign strategy to apply (Option {option.upper()}):\n{strategies[:1500]}"
    prompt = header + context + strategy_block + rules
    # Nova Canvas text prompt limit is 1024 characters.
    return prompt[:1024]


def generate_image_gemini(prompt):
    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    req = urllib.request.Request(
        GEMINI_ENDPOINT,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Gemini image request failed ({exc.code})") from exc

    candidates = payload.get("candidates") or []
    for candidate in candidates:
        parts = (candidate.get("content") or {}).get("parts") or []
        for part in parts:
            inline_data = part.get("inlineData")
            if inline_data and inline_data.get("data"):
                return inline_data["data"]
    raise RuntimeError("Gemini returned no image")


HF_PROVIDERS = ["together", "nscale", "fal-ai"]


def _hf_request(url, payload, token, accept="application/json"):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": accept,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def generate_image_huggingface(prompt):
    """Hugging Face Inference Providers (OpenAI-style images API, billed to the
    free monthly HF credits). Tries each provider until one returns an image."""
    errors = []
    for provider in HF_PROVIDERS:
        try:
            if provider == "fal-ai":
                raw = _hf_request(
                    f"https://router.huggingface.co/fal-ai/{HF_IMAGE_MODEL}",
                    {"prompt": prompt[:1000]},
                    HF_TOKEN,
                )
                payload = json.loads(raw)
                images = payload.get("images") or []
                if images and images[0].get("url"):
                    with urllib.request.urlopen(images[0]["url"], timeout=15) as img:
                        return base64.b64encode(img.read()).decode("ascii")
            else:
                raw = _hf_request(
                    f"https://router.huggingface.co/{provider}/v1/images/generations",
                    {
                        "model": HF_IMAGE_MODEL,
                        "prompt": prompt[:1000],
                        "response_format": "b64_json",
                        "n": 1,
                    },
                    HF_TOKEN,
                )
                data = (json.loads(raw).get("data") or [{}])[0]
                if data.get("b64_json"):
                    return data["b64_json"]
            errors.append(f"{provider}: no image")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:120].decode("utf-8", "ignore").replace(chr(10), " ")
            errors.append(f"{provider} {exc.code} {detail}")
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    raise RuntimeError("Hugging Face failed (" + "; ".join(errors) + ")")


def generate_image_pollinations(prompt):
    """Free, key-less last resort. Returns base64 of the JPEG it serves.

    The service sheds load with 5xx/429 when several images are requested at
    once, so retry a few times within the Lambda's time budget.
    """
    deadline = time.monotonic() + 22
    last_error = "no attempt made"
    for attempt in range(4):
        url = (
            "https://image.pollinations.ai/prompt/"
            + urllib.parse.quote(prompt[:800])
            + f"?width=1024&height=1024&nologo=true&model=flux&seed={random.randint(1, 999999)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "EcoLens/1.0"})
        remaining = deadline - time.monotonic()
        if remaining < 4:
            break
        try:
            with urllib.request.urlopen(req, timeout=min(remaining, 15)) as resp:
                data = resp.read()
            if data:
                return base64.b64encode(data).decode("ascii")
            last_error = "returned no image"
        except urllib.error.HTTPError as exc:
            last_error = f"failed ({exc.code})"
        except Exception as exc:
            last_error = f"failed ({exc})"
        time.sleep(1.5 + attempt)
    raise RuntimeError(f"Pollinations image request {last_error}")


def generate_image_bedrock(model_id, prompt):
    request_body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "width": 1024,
            "height": 1024,
            "cfgScale": 7.5,
            "quality": "standard",
        },
    }
    response = bedrock.invoke_model(modelId=model_id, body=json.dumps(request_body))
    payload = json.loads(response["body"].read())
    images = payload.get("images") or []
    if not images:
        raise RuntimeError(f"{model_id} returned no images")
    return images[0]


def generate_image(option, fields, strategies):
    prompt = build_prompt(option, fields, strategies)
    errors = []
    for model_id, max_chars in IMAGE_MODELS:
        try:
            return generate_image_bedrock(model_id, prompt[:max_chars])
        except Exception as exc:
            print(f"{model_id} image generation failed: {exc}")
            errors.append(f"{model_id}: {exc}")
    if GEMINI_API_KEY:
        try:
            return generate_image_gemini(prompt)
        except Exception as exc:
            errors.append(str(exc))
    if HF_TOKEN:
        try:
            return generate_image_huggingface(prompt)
        except Exception as exc:
            errors.append(str(exc))
    try:
        return generate_image_pollinations(prompt)
    except Exception as exc:
        errors.append(str(exc))
    raise RuntimeError(" | ".join(errors))


def _response(status, body_dict):
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps(body_dict),
    }


def handler(event, context):
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "POST"
    )
    if method == "OPTIONS":
        return _response(200, {"ok": True})

    try:
        raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        body = json.loads(raw)
    except Exception:
        body = {}

    option = body.get("option", "A")
    fields = body.get("fields") or {}
    strategies = body.get("strategies") or ""

    try:
        image_b64 = generate_image(option, fields, strategies)
    except Exception as exc:
        return _response(500, {"error": str(exc)})

    return _response(200, {"image_base64": image_b64})
