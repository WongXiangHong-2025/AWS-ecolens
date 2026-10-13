"""
EcoLens — Packaging Redesign Visual (image generation widget).

Standard Lambda handler (no Flask). Generates ONE combined concept image that
shows all three redesign options (A, B and C) side by side, each labelled:
the frontend POSTs {"fields": {...}, "strategies": "<text>"} and receives
{"image_base64": "..."} back. Calls amazon.nova-canvas-v1:0 via invoke_model
and returns the base64 PNG as JSON.
"""
import base64
import json
import os

import boto3

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-5"))
IMAGE_MODEL_ID = "amazon.nova-canvas-v1:0"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
    "Content-Type": "application/json",
}

# The essential instructions come first so the 1024-character Nova Canvas
# prompt limit only ever truncates the trailing context, never the rules.
HEADER = (
    "ONE photorealistic product photo: THREE redesigned versions of the SAME package "
    "side by side in one frame, each labelled with a large letter A, B or C below it. "
    "A=Quick Win: same format, barely noticeable changes (thinner material, recycling "
    "symbol, slightly smaller). "
    "B=Balanced: same format, noticeable practical changes (material substitution, "
    "recyclability markings, modest structural change). "
    "C=Ambitious: bold transformation (mono-material, paper or kraft structure), still "
    "retail-ready. "
    "All three: keep brand colours, logo and identity; studio lighting, clean neutral "
    "background; closed sealed packaging only; no hands, people or diagrams; no text "
    "except the A, B, C labels."
)

# Nova Canvas text prompt limit.
MAX_PROMPT = 1024


def _clip(value, limit):
    return (value or "")[:limit]


def build_prompt(fields, strategies):
    f = fields or {}
    context = (
        f" Product: {_clip(f.get('Product Name and Type'), 50)}."
        f" Category: {_clip(f.get('Product Category'), 30)}."
        f" Materials: {_clip(f.get('Current Packaging Materials'), 70)}."
        f" Branding: {_clip(f.get('Branding Requirements'), 70)}."
    )
    prompt = HEADER + context
    # Fill whatever room is left with the strategies text.
    remaining = MAX_PROMPT - len(prompt) - len(" Strategies: ")
    if strategies and remaining > 40:
        prompt += f" Strategies: {_clip(strategies, remaining)}"
    return prompt[:MAX_PROMPT]


def generate_image(fields, strategies):
    prompt = build_prompt(fields, strategies)
    request_body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            # Wide frame so the three labelled options sit side by side.
            "width": 1792,
            "height": 1024,
            "cfgScale": 7.5,
            "quality": "standard",
        },
    }
    response = bedrock.invoke_model(modelId=IMAGE_MODEL_ID, body=json.dumps(request_body))
    payload = json.loads(response["body"].read())
    images = payload.get("images") or []
    if not images:
        raise RuntimeError("Nova Canvas returned no images")
    return images[0]


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

    fields = body.get("fields") or {}
    strategies = body.get("strategies") or ""

    try:
        image_b64 = generate_image(fields, strategies)
    except Exception as exc:
        return _response(500, {"error": str(exc)})

    return _response(200, {"image_base64": image_b64})
