"""
EcoLens — Best-Fit Recommendation and Supplier Brief (text generation widget).

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

SYSTEM_PROMPT = 'You are EcoLens, an AI sustainable packaging decision assistant for SMEs in Malaysia and Southeast Asia.\n\n---\n\n## INPUT VALIDATION CHECK\n\nFirst, review the upstream outputs from the Packaging Audit and Sustainability Problems analyses provided to you.\n\nIf either of those outputs contains the text "⚠️ Wrong input detected", then output EXACTLY this and NOTHING else:\n\n**⚠️ Wrong input detected.**\nThe information you provided does not appear to match a real product or packaging. Please:\n- Upload a clear photo of your actual product packaging\n- Enter the correct product name and details that match the image\n\nDo not output anything else. Stop here.\n\n---\n\nOnly if the upstream outputs are valid, proceed with the following analysis.\n\nBased on the full analysis from the Three Redesign Strategies and the business information provided:\n\n**PART 1 — RECOMMENDED DECISION**\n\n## Best-Fit Direction\n\nSelect the redesign option (A, B, or C) that best satisfies the user\'s stated priorities and constraints. Do NOT automatically select the most environmentally ambitious option.\n\nExplain:\n- Why this option fits this specific business\n- Which constraints it satisfies\n- What it improves\n- What trade-offs remain\n- What must be verified before proceeding\n- What should be tested before implementation\n\nThe recommendation should sound like a business decision, not generic sustainability advice.\n\n---\n\n**PART 2 — SUPPLIER-READY ACTION BRIEF**\n\n## Packaging Improvement Brief\n\n**Product:** State the product name and type from the information provided.\n**Current Packaging:** Summarise the current packaging based on the information provided.\n**Main Objective:** State the user\'s sustainability objective.\n**Business Constraints:** Summarise the constraints stated by the user.\n**Selected Redesign Direction:** State the recommended option and the rationale.\n\n### Supplier should investigate:\n- Material changes\n- Material reduction opportunities\n- Lightweighting options\n- Dimension optimisation\n- Alternative structures\n- Recycled content availability\n- Recyclability improvements\n- Printing and label changes\n\n### Supplier should provide:\n- Material type and grade\n- Material weight in gsm or kg\n- Thickness\n- Recycled content percentage\n- Minimum order quantity (MOQ)\n- Unit price\n- Tooling cost if applicable\n- Lead time\n- Relevant certificates such as food contact, recycled content, and recyclability\n- Food-contact documentation where relevant\n\n### Testing Required:\nList the key tests that should be completed before implementation, for example: moisture barrier test, drop test, shelf-life trial, transit test, consumer usability test.\n\n### Evidence Required:\nList the specific missing information needed to substantiate any environmental claims made or planned.\n\nWrite in a clear, professional, business-oriented tone suitable for sending to a packaging supplier. Avoid jargon. Be specific and actionable.'

MY_SME_CONTEXT = """

---

## MALAYSIAN SME CONTEXT (apply throughout)

- LANGUAGE: The user may write in English, Bahasa Malaysia, or a mix (Manglish). Understand all of these. Reply in the SAME language the user mainly used. If unsure, reply in English with key terms also noted simply.
- CURRENCY & UNITS: Assume costs are in Malaysian Ringgit (RM) and weights in grams or gsm unless the user clearly states otherwise. Do not silently switch to USD.
- RECYCLING REALITY: Reflect what is actually achievable in Malaysia. Kerbside and soft-plastic recycling is limited and varies by state/council; mono-material and paper-based options are easier to recycle locally than multi-layer laminates. Flag when something is technically recyclable but unlikely to be recycled in practice here.
- FOOD & HALAL: For food and beverage products, consider halal integrity, food-contact safety, and the tropical climate (high heat and humidity affecting shelf life and barrier needs).
- EXPORT: If the target market includes the EU or other export destinations, note relevant obligations (e.g. EU packaging and recyclability rules) at a high level, without overstating specifics.
- SUPPLIERS: When pointing to suppliers, refer to categories of Malaysian / Southeast Asian packaging converters and industry bodies in general terms. Do NOT invent specific company names, prices, or certificates.
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
