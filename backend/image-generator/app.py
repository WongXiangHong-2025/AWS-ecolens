"""
EcoLens — Packaging Redesign Visual (image generation widget).

Standard Lambda handler (no Flask). Serves Options A, B and C: the frontend
POSTs {"option": "A"|"B"|"C", "fields": {...}, "strategies": "<that option's
Step 3 text>", "image_data": "<base64 photo>", "image_mime": "image/jpeg"}
and receives {"image_base64": "...", "mime": "image/png"} back.

The user's packaging photo is used as a reference so the redesign keeps the
real product's look (brand, label, colours, shape). Providers are tried in
order until one succeeds, all inside one time budget so the request never
outlives API Gateway's 30 s limit:

  1. Bedrock Stable Diffusion 3.5 Large — image-to-image from the photo
     (text-to-image without one). Replaces Nova Canvas and Titan Image v2,
     which AWS retired in 2026.
  2. Gemini image model   — edits the photo (if GEMINI_API_KEY is set)
  3. Hugging Face FLUX    — text only (if HF_TOKEN is set)
  4. Pollinations         — free, text-only last resort
"""
import base64
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3
from botocore.config import Config

# Stable Diffusion 3.5 Large is served from us-west-2.
REGION = os.environ.get("BEDROCK_REGION", "us-west-2")
IMAGE_MODEL = os.environ.get("BEDROCK_IMAGE_MODEL", "stability.sd3-5-large-v1:0")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_IMAGE_MODEL = os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_IMAGE_MODEL}:generateContent"
)

# API Gateway HTTP APIs cut requests off at 30 s; keep a margin for the response.
BUDGET_SECONDS = float(os.environ.get("IMAGE_BUDGET_SECONDS", "26"))

# No hidden SDK retries: they can silently use up the whole time budget. We
# retry throttling ourselves, once, and then move on to the next provider.
bedrock = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=Config(connect_timeout=4, read_timeout=22, retries={"max_attempts": 1, "mode": "standard"}),
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}

# How far each option may move away from the reference photo (SD3.5 image-to-image
# strength: 0 = keep the photo as it is, 1 = ignore it entirely).
OPTION_STYLE = {
    "A": ("a subtly improved version", 0.35,
          "Keep the exact same pack shape, size, lid and label layout; only the small changes listed."),
    "B": ("a moderately redesigned version", 0.55,
          "Keep the brand, logo, label design and colours; the pack structure may change as described."),
    "C": ("a bold next-generation version", 0.75,
          "Keep the brand name, logo and colour palette recognisable; the pack format may change as described."),
}

NEGATIVE = ("blurry, distorted or misspelled logo, garbled text, extra products, hands, people, "
            "diagram, collage, infographic, watermark, cartoon")


class OutOfTime(Exception):
    pass


class Budget:
    def __init__(self, seconds):
        self.end = time.monotonic() + seconds

    def left(self):
        return self.end - time.monotonic()

    def need(self, seconds):
        if self.left() < seconds:
            raise OutOfTime(f"skipped (only {self.left():.0f}s left)")


def _clean(text, limit):
    text = re.sub(r"[*_#`>|]+", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text


def option_changes(strategies):
    """Pull the option's name and its 'Changes' bullets out of the Step 3 text."""
    lines = [l.strip() for l in (strategies or "").splitlines() if l.strip()]
    if not lines:
        return ""
    title = lines[0]
    m = re.search(r"(?:OPTION|PILIHAN)\s+[ABC]\s*[—–-]+\s*(.*)", title, re.I)
    name = m.group(1).split(":")[-1].strip() if m else ""
    changes, grab = [], False
    for l in lines[1:]:
        if re.match(r"[-*]?\s*\**\s*(Changes|Perubahan)\b", l, re.I):
            grab = True
            changes.append(re.sub(r"^[-*]?\s*\**\s*(Changes|Perubahan)\s*:?\**\s*:?", "", l, flags=re.I))
            continue
        if grab and re.match(r"[-*]\s*\**\s*[A-Z][^:]{0,40}:", l):  # next labelled field
            break
        if grab:
            changes.append(l.lstrip("-* "))
    body = "; ".join(c for c in changes if c) or " ".join(lines[1:6])
    return _clean(f"{name}: {body}" if name else body, 420)


def build_prompt(option, fields, strategies, with_reference):
    """Short, prioritised prompt: the change to show comes first, so a length
    limit trims the least important context instead of the instructions."""
    look, _, keep = OPTION_STYLE.get(option, OPTION_STYLE["A"])
    f = fields or {}
    product = _clean(re.split(r"\s\(|,", f.get("Product Name and Type", "") or "the product")[0], 80)
    changes = option_changes(strategies) or "more sustainable materials with clear recycling marks"
    ref = "the packaging in the reference photo" if with_reference else (
        f"the current packaging ({_clean(f.get('Current Packaging Materials', ''), 120)})")
    branding = _clean(f.get("Branding Requirements", ""), 160)
    parts = [
        f"Photorealistic studio product photo of {look} of {ref} for {product}.",
        f"Redesign: {changes}.",
        keep,
        "Single closed pack, front view, soft studio light, plain light background, sharp readable logo.",
    ]
    if branding:
        parts.append(f"Branding: {branding}.")
    return " ".join(parts)


def _is_image(b64):
    try:
        head = base64.b64decode(b64[:24] + "=" * (-len(b64[:24]) % 4))
    except Exception:
        return False
    return head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8")


def mime_of(b64):
    head = base64.b64decode(b64[:24] + "=" * (-len(b64[:24]) % 4))
    return "image/jpeg" if head.startswith(b"\xff\xd8") else "image/png"


# Error names Bedrock raises when it is shedding load.
_THROTTLE_MARKERS = ("throttl", "toomanyrequests", "serviceunavailable", "service unavailable",
                     "slow down", "rate exceeded", "429", "503")


def _is_throttle(exc):
    return any(m in f"{type(exc).__name__} {exc}".lower() for m in _THROTTLE_MARKERS)


def generate_image_bedrock(prompt, option, reference, budget):
    """Stable Diffusion 3.5 Large on Bedrock: image-to-image from the user's photo
    (how much it may change depends on the option), or text-to-image without one."""
    _, strength, _ = OPTION_STYLE.get(option, OPTION_STYLE["A"])
    request_body = {"prompt": prompt, "negative_prompt": NEGATIVE, "output_format": "jpeg"}
    if reference:
        request_body.update({"mode": "image-to-image", "image": reference["data"], "strength": strength})
    else:
        request_body.update({"mode": "text-to-image", "aspect_ratio": "1:1"})
    for attempt in range(2):
        budget.need(12)  # a generation takes several seconds; never start one that could outlive the budget
        try:
            response = bedrock.invoke_model(modelId=IMAGE_MODEL, body=json.dumps(request_body))
            payload = json.loads(response["body"].read())
            reason = (payload.get("finish_reasons") or [None])[0]
            if reason:  # e.g. the content filter stopped it
                raise RuntimeError(f"finished with: {reason}")
            images = payload.get("images") or []
            if not images:
                raise RuntimeError("returned no images")
            return images[0]
        except Exception as exc:
            if _is_throttle(exc) and attempt == 0:
                time.sleep(1.0 + random.uniform(0, 0.5))
                continue
            raise


def generate_image_gemini(prompt, reference, budget):
    budget.need(8)
    parts = []
    if reference:
        parts.append({"inlineData": {"mimeType": reference["mime"], "data": reference["data"]}})
        prompt = ("Edit this product photo. " + prompt +
                  " Keep the same brand name, logo and label text spelled exactly as in the photo.")
    parts.append({"text": prompt})
    req = urllib.request.Request(
        GEMINI_ENDPOINT,
        data=json.dumps({"contents": [{"parts": parts}],
                         "generationConfig": {"responseModalities": ["IMAGE"]}}).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=min(22, budget.left() - 1)) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    for candidate in payload.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData")
            if inline and inline.get("data"):
                return inline["data"]
    raise RuntimeError("returned no image")


HF_PROVIDERS = ["together", "nscale", "fal-ai"]


def _hf_request(url, payload, timeout, accept="application/json"):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json", "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def generate_image_huggingface(prompt, budget):
    """Hugging Face Inference Providers (text only)."""
    errors = []
    for provider in HF_PROVIDERS:
        try:
            budget.need(6)
            timeout = min(15, budget.left() - 1)
            if provider == "fal-ai":
                payload = json.loads(_hf_request(
                    f"https://router.huggingface.co/fal-ai/{HF_IMAGE_MODEL}", {"prompt": prompt[:1000]}, timeout))
                images = payload.get("images") or []
                if images and images[0].get("url"):
                    with urllib.request.urlopen(images[0]["url"], timeout=min(8, budget.left() - 1)) as img:
                        return base64.b64encode(img.read()).decode("ascii")
            else:
                raw = _hf_request(
                    f"https://router.huggingface.co/{provider}/v1/images/generations",
                    {"model": HF_IMAGE_MODEL, "prompt": prompt[:1000], "response_format": "b64_json", "n": 1},
                    timeout)
                data = (json.loads(raw).get("data") or [{}])[0]
                if data.get("b64_json"):
                    return data["b64_json"]
            errors.append(f"{provider}: no image")
        except OutOfTime:
            raise
        except urllib.error.HTTPError as exc:
            errors.append(f"{provider} HTTP {exc.code}")
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
    raise RuntimeError("; ".join(errors))


def generate_image_pollinations(prompt, budget):
    """Free, key-less, text-only last resort. It rate-limits back-to-back
    requests, so retry with a short back-off while time allows."""
    last_error = "no attempt made"
    for attempt in range(4):
        budget.need(6)
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:800])
               + f"?width=1024&height=1024&nologo=true&model=flux&seed={random.randint(1, 999999)}")
        req = urllib.request.Request(url, headers={"User-Agent": "EcoLens/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=min(18, budget.left() - 1)) as resp:
                data = resp.read()
            if data:
                return base64.b64encode(data).decode("ascii")
            last_error = "returned no image"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(min(1.5 + attempt * 1.5, max(0, budget.left() - 6)))
    raise RuntimeError(last_error)


def generate_image(option, fields, strategies, reference):
    budget = Budget(BUDGET_SECONDS)
    errors = []

    def attempt(label, fn):
        try:
            result = fn()
            if result and _is_image(result):
                return result
            errors.append(f"{label}: not an image")
        except Exception as exc:
            print(f"{label} failed: {exc}")
            errors.append(f"{label}: {exc}")
        return None

    full_prompt = build_prompt(option, fields, strategies, bool(reference))
    image = attempt("sd3.5-large", lambda: generate_image_bedrock(full_prompt, option, reference, budget))
    if image:
        return image
    if GEMINI_API_KEY:
        image = attempt("gemini", lambda: generate_image_gemini(full_prompt, reference, budget))
        if image:
            return image
    # The remaining providers cannot see the photo, so describe the pack in words.
    text_prompt = build_prompt(option, fields, strategies, False)
    if HF_TOKEN:
        image = attempt("huggingface", lambda: generate_image_huggingface(text_prompt, budget))
        if image:
            return image
    image = attempt("pollinations", lambda: generate_image_pollinations(text_prompt, budget))
    if image:
        return image
    raise RuntimeError(" | ".join(errors))


def _response(status, body_dict):
    return {"statusCode": status, "headers": CORS_HEADERS, "body": json.dumps(body_dict)}


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

    option = str(body.get("option", "A")).upper()
    fields = body.get("fields") or {}
    strategies = body.get("strategies") or ""
    reference = None
    if body.get("image_data") and str(body.get("image_mime", "")).startswith("image/"):
        reference = {"data": body["image_data"], "mime": body["image_mime"]}

    try:
        image_b64 = generate_image(option, fields, strategies, reference)
    except Exception as exc:
        return _response(502, {"error": str(exc)})

    return _response(200, {"image_base64": image_b64, "mime": mime_of(image_b64)})
