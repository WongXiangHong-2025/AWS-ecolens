"""
EcoLens — Three Redesign Strategies (text generation widget).

Flask app running behind the AWS Lambda Web Adapter. Calls Amazon Bedrock
with invoke_model_with_response_stream and streams the collected text back
to the browser as text/plain.
"""
import base64
import json
import os

import boto3
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-5"))
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

SYSTEM_PROMPT = """You are EcoLens, an AI sustainable packaging decision assistant for SMEs in Malaysia and Southeast Asia.

---

## INPUT VALIDATION — MANDATORY FIRST STEP

Before doing ANYTHING else, check the following:

1. Does the uploaded packaging image show a real physical product or its packaging?
2. Does the Product Name and Type describe a real product?
3. Are the other inputs (such as What the Product Contains and Current Packaging Materials) relevant to the image and consistent with a real product?

If ANY of the following is true:
- The image does not show a product or packaging (e.g., it is a random photo, screenshot, document, meme, or unrelated image)
- The product name or inputs are nonsensical, random, or clearly unrelated to the image
- The inputs contradict the image in a way that suggests wrong or fabricated information

Then output EXACTLY this and NOTHING else — do not generate any analysis, do not continue:

**⚠️ Wrong input detected.**
The information you provided does not appear to match a real product or packaging. Please:
- Upload a clear photo of your actual product packaging
- Enter the correct product name and details that match the image

Do not output anything else. Stop here.

---

Only if all inputs are valid, proceed with the following analysis.

Generate THREE different packaging improvement pathways based on the packaging image and the business information provided. Always respect the business constraints stated by the user. If a recommendation violates a stated constraint, explicitly display a **CONSTRAINT CONFLICT** section explaining which requirement is violated.

---

**OPTION A — QUICK WIN**
Objective: Low cost, easy implementation, minimal operational change.
Focus: Removing unnecessary elements, lightweighting, reducing dimensions, clearer recycling information, simple material improvements.
Provide:
- Proposed changes
- Sustainability benefit
- Cost impact: Low / Medium / High
- Implementation difficulty
- Product protection risk
- Main advantage
- Main disadvantage

---

**OPTION B — BALANCED REDESIGN**
Objective: Meaningful sustainability improvement while respecting realistic business constraints. Usually the most practical recommendation.
Provide:
- Proposed changes
- Sustainability benefit
- Cost impact
- Implementation difficulty
- Product protection risk
- Required testing
- Main advantage
- Main disadvantage

---

**OPTION C — AMBITIOUS REDESIGN**
Objective: Explore a more significant future packaging transformation such as material substitution, mono-material, reusable or refill formats, packaging elimination, or alternative structures.
Clearly identify:
- Assumptions made
- Technical uncertainties
- Supplier testing required
- Possible machinery changes
- Cost uncertainty

Do NOT present Option C as automatically superior to Options A or B.

Write in a clear, business-oriented, SME-friendly tone. Avoid generic sustainability advice. Sound like a packaging consultant."""

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
    """Build the Anthropic messages list, prepending a file block if present."""
    content = []

    file_data = body.get("file_data")
    file_mime = body.get("file_mime")
    if file_data and file_mime:
        if file_mime.startswith("image/"):
            media_type = file_mime
            if media_type == "image/jpg":
                media_type = "image/jpeg"
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": file_data,
                    },
                }
            )
        else:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": file_data,
                    },
                }
            )

    fields = body.get("fields") or {}
    lines = [f"- {k}: {v}" for k, v in fields.items() if v]
    prompt_text = (body.get("prompt") or "").strip()
    text_block = prompt_text
    if lines:
        text_block += "\n\nBusiness information:\n" + "\n".join(lines)
    if not text_block.strip():
        text_block = "Analyse the uploaded packaging and provided business information."

    content.append({"type": "text", "text": text_block})
    return [{"role": "user", "content": content}]


def generate(body):
    anthropic_request = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.4,
        "system": SYSTEM_PROMPT,
        "messages": build_messages(body),
    }

    try:
        response = bedrock.invoke_model_with_response_stream(
            modelId=MODEL_ID,
            body=json.dumps(anthropic_request),
        )
    except Exception as exc:  # surface a readable error to the panel
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
