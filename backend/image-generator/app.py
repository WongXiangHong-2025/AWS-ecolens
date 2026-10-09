"""
EcoLens — Packaging Redesign Visual (image generation widget).

Standard Lambda handler (no Flask). Serves Options A, B and C: the frontend
POSTs {"option": "A"|"B"|"C", "fields": {...}, "strategies": "<text>"} and
receives {"image_base64": "..."} back. Calls amazon.nova-canvas-v1:0 via
invoke_model and returns the base64 PNG as JSON.
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


def generate_image(option, fields, strategies):
    prompt = build_prompt(option, fields, strategies)
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

    option = body.get("option", "A")
    fields = body.get("fields") or {}
    strategies = body.get("strategies") or ""

    try:
        image_b64 = generate_image(option, fields, strategies)
    except Exception as exc:
        return _response(500, {"error": str(exc)})

    return _response(200, {"image_base64": image_b64})
