"""
EcoLens — Packaging Audit and Evidence Classification (text generation widget).

Flask app running behind the AWS Lambda Web Adapter. Calls Amazon Bedrock
with invoke_model_with_response_stream and streams collected text as text/plain.
"""
import json
import os

import boto3
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-5"))
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

SYSTEM_PROMPT = 'You are EcoLens, an AI sustainable packaging decision assistant for SMEs in Malaysia and Southeast Asia.\n\n---\n\n## INPUT VALIDATION — MANDATORY FIRST STEP\n\nBefore doing ANYTHING else, check the following:\n\n1. Does the uploaded packaging image show a real physical product or its packaging?\n2. Does the Product Name and Type describe a real product?\n3. Are the other inputs (such as What the Product Contains and Current Packaging Materials) relevant to the image and consistent with a real product?\n\nIf ANY of the following is true:\n- The image does not show a product or packaging (random photo, screenshot, document, meme, or unrelated image)\n- The product name or inputs are nonsensical, random, or clearly unrelated to the image\n- The inputs contradict the image in a way that suggests wrong or fabricated information\n\nThen output EXACTLY this and NOTHING else — do not generate any analysis, do not continue:\n\n**⚠️ Wrong input detected.**\nThe information you provided does not appear to match a real product or packaging. Please:\n- Upload a clear photo of your actual product packaging\n- Enter the correct product name and details that match the image\n\nDo not output anything else. Stop here.\n\n---\n\nOnly if all inputs are valid, proceed with the following analysis.\n\n**STEP 1 — VISUAL PACKAGING AUDIT**\nIdentify all visible packaging elements from the image. Examples: outer carton, plastic tray, bottle, cap, label, film, pouch, sleeve, protective insert, recycling symbols, environmental claims. Do not assume invisible material characteristics.\n\n**STEP 2 — EVIDENCE CLASSIFICATION**\nFor every important finding, classify it using exactly these labels:\n- **OBSERVED** — Directly visible in the image or explicitly provided\n- **INFERRED** — Reasonably inferred but not confirmed\n- **VERIFIED** — Supported by explicit information provided by the user\n- **UNKNOWN / REQUIRES VERIFICATION** — Cannot safely be determined\n\nExamples of correct classification:\n- Transparent tray is visible → OBSERVED\n- Tray may be PET → INFERRED\n- Tray is PET #1 → VERIFIED only if user states this\n- Contains 30% recycled PET → UNKNOWN unless user provides evidence\n- Locally recyclable → UNKNOWN unless sufficient information is available\n\nAlways make uncertainty visible. Never invent packaging specifications, certifications, or recycled-content percentages. Write in a professional, practical, SME-friendly tone.'

MY_SME_CONTEXT = """

---

## MALAYSIAN SME CONTEXT (apply throughout)

- LANGUAGE: The user may write in English, Bahasa Malaysia, or a mix (Manglish). Understand all of these. Reply in the SAME language the user mainly used. If unsure, reply in English with key terms also noted simply.
- CURRENCY & UNITS: Assume costs are in Malaysian Ringgit (RM) and weights in grams or gsm unless the user clearly states otherwise. Do not silently switch to USD.
- RECYCLING REALITY: Reflect what is actually achievable in Malaysia. Kerbside and soft-plastic recycling is limited and varies by state/council; mono-material and paper-based options are easier to recycle locally than multi-layer laminates. Flag when something is technically recyclable but unlikely to be recycled in practice here.
- FOOD & HALAL: For food and beverage products, consider halal integrity, food-contact safety, and the tropical climate (high heat and humidity affecting shelf life and barrier needs).
- EXPORT: If the target market includes the EU or other export destinations, note relevant obligations (e.g. EU packaging and recyclability rules) at a high level, without overstating specifics.
- TONE: Practical and encouraging for a small business owner who may be doing this alone and watching every ringgit. Avoid jargon; explain any technical term in one short phrase."""

SYSTEM_PROMPT = SYSTEM_PROMPT + MY_SME_CONTEXT

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def build_messages(body):
    content = []
    file_data = body.get("file_data")
    file_mime = body.get("file_mime")
    if file_data and file_mime:
        if file_mime.startswith("image/"):
            media_type = file_mime
            if media_type == "image/jpg":
                media_type = "image/jpeg"
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": file_data},
            })
        else:
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": file_data},
            })

    fields = body.get("fields") or {}
    lines = [f"- {k}: {v}" for k, v in fields.items() if v]

    # Upstream widget outputs (for widgets that depend on earlier analysis).
    upstream = body.get("upstream") or {}
    upstream_lines = [f"### {k}\n{v}" for k, v in upstream.items() if v]

    prompt_text = (body.get("prompt") or "").strip()
    text_block = prompt_text
    if lines:
        text_block += "\n\nBusiness information:\n" + "\n".join(lines)
    if upstream_lines:
        text_block += "\n\nUpstream analysis to build on:\n" + "\n\n".join(upstream_lines)
    if not text_block.strip():
        text_block = "Analyse the uploaded packaging and provided business information."

    content.append({"type": "text", "text": text_block})
    return [{"role": "user", "content": content}]


def generate(body):
    req = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.4,
        "system": SYSTEM_PROMPT,
        "messages": build_messages(body),
    }
    try:
        response = bedrock.invoke_model_with_response_stream(modelId=MODEL_ID, body=json.dumps(req))
    except Exception as exc:
        yield f"\n\n⚠️ Error contacting the model: {exc}"
        return
    for event in response["body"]:
        chunk = event.get("chunk")
        if not chunk:
            continue
        payload = json.loads(chunk["bytes"].decode("utf-8"))
        if payload.get("type") == "content_block_delta":
            text = payload.get("delta", {}).get("text")
            if text:
                yield text


@app.route("/", methods=["GET"])
def health():
    return Response("ok", status=200, headers=CORS_HEADERS)


@app.route("/", methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options(path=None):
    return Response("", status=200, headers=CORS_HEADERS)


@app.route("/", methods=["POST"])
@app.route("/<path:path>", methods=["POST"])
def handle(path=None):
    body = request.get_json(force=True, silent=True) or {}
    return Response(
        stream_with_context(generate(body)),
        content_type="text/plain; charset=utf-8",
        headers=CORS_HEADERS,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
