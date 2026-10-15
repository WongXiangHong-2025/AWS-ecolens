"""
EcoLens — Best-Fit Recommendation and Supplier Brief (text generation widget).

Flask app running behind the AWS Lambda Web Adapter. Calls Amazon Bedrock
with invoke_model_with_response_stream and streams collected text as text/plain.
"""
import json
import os
import time
import traceback

import boto3
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-5"))
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

# API Gateway HTTP API cuts requests off at 30s and the Lambda timeout is 29s.
# The response is buffered, so stop generating before then and return what we
# have instead of letting the function time out with an HTTP 500.
DEADLINE_SECONDS = float(os.environ.get("GENERATION_DEADLINE_SECONDS", "24"))

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

SYSTEM_PROMPT = """You are EcoLens, an AI sustainable packaging decision assistant for SMEs in Malaysia and Southeast Asia.

This is STEP 5 of 5 of the EcoLens report: RECOMMENDATION & SUPPLIER BRIEF. Steps 1–4 (audit, problems, strategies, trade-off comparison) are provided as upstream analysis. Choose ONE of the Step 3 options (A, B or C), using its exact name, and make sure your reasoning matches the Step 4 comparison. Do not automatically choose the most ambitious option. Prefer an option that is within budget; choose an over-budget option only if it is clearly worth it, and then name the in-budget fallback.

## WHAT TO WRITE
Key points: first bullet "Go with Option X — <name>: <main reason>". If that option is over budget, say so in this bullet. Then the 2–3 most important next steps, each as one short action.

Details:
## Recommended decision
- **Why this option fits:** for this business and its constraints
- **What it improves:** linked to the Step 2 problems
- **Trade-offs to accept:** what gets worse or stays risky
- **Check before committing:** what must be verified or tested first
- **Fallback:** which option to use if testing fails

## Supplier brief
**Product:** · **Current packaging:** · **Goal:** · **Constraints:** · **Chosen direction:** (one line each)

### Ask the supplier to look into
3–5 short bullets specific to the chosen option.

### Ask the supplier to provide
Material type and grade, weight (gsm or g), thickness, recycled content %, MOQ, unit price in RM, tooling cost, lead time, and certificates (food contact, recycled content, recyclability) where relevant.

### Tests before switching
The tests that must pass (e.g. moisture/shelf-life trial in tropical conditions, drop and transit test).

### Evidence needed for any eco claim
What proof is needed before printing any environmental claim on the pack.

Write the supplier brief so it can be sent to a packaging supplier as-is."""

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

REPORT_RULES = """

---

## HOW TO WRITE THIS STEP
The EcoLens report is written in five steps, in this order: 1 Packaging audit → 2 Problems found → 3 Three redesign strategies → 4 Trade-off comparison → 5 Recommendation & supplier brief. Earlier steps may be given to you as "Upstream analysis". Build on them: keep the same facts, component names and option names, and never contradict them.
- Stay inside this step. Never write content that belongs to another step.
- Never mention, repeat or comment on input validation (only Step 1 checks inputs).
- No greetings, no sign-offs, no offers of further help, and no questions to the reader. This is a report, not a chat.
- Never recommend or name specific supplier companies, brands or certification bodies.
- No invented numbers. Never state performance or business figures the user did not give: no carbon or emission %, no % improvements (e.g. "reduces oxygen by 70%"), no supplier discounts, no seconds per unit, no order volumes, no capital costs, no market statistics. Typical material specs for a supplier to confirm (e.g. film thickness) are allowed.
- Costs: give cost changes only as a rough RM range per unit marked "(estimate)", and only if a current unit cost is given. If a "Budget Limit (calculated)" is given, use exactly those numbers, compare every estimate with it, and say plainly "within budget" or "over budget". Never call an estimate within budget if it is above the limit.
- Use plain, everyday words for a busy small-business owner. Explain any technical term in a few words the first time.

## OUTPUT FORMAT (follow exactly)
1. Start with the heading "## Key points" followed by 3–5 bullets. Each bullet is ONE short sentence of at most 18 words that can be understood on its own. Start it with the main idea, e.g. "Option B: ...".
2. Then a line containing exactly: [[DETAILS]]
3. Then the detailed explanation as described above, using ## / ### headings, short paragraphs and bullets.
- Write labelled lines as "- **Label:** text". Put sub-points in a nested list indented by two spaces.
- Each bullet at most 25 words; each paragraph at most 3 sentences.
- HARD LENGTH LIMIT: the response must finish well inside the word limit below. If space is short, cut detail; never stop in the middle of a section.
Keep the whole response under about 600 words."""

SYSTEM_PROMPT = SYSTEM_PROMPT + MY_SME_CONTEXT + REPORT_RULES

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
    started = time.monotonic()
    req = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2500,
        "temperature": 0.4,
        "system": SYSTEM_PROMPT,
        "messages": build_messages(body),
    }
    try:
        response = bedrock.invoke_model_with_response_stream(modelId=MODEL_ID, body=json.dumps(req))
    except Exception as exc:
        traceback.print_exc()
        yield f"\n\n⚠️ Error contacting the model: {type(exc).__name__}: {exc}"
        return
    for event in response["body"]:
        if time.monotonic() - started > DEADLINE_SECONDS:
            return  # out of time: end quietly with what was written
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
    try:
        body = request.get_json(force=True, silent=True) or {}
        return Response(
            stream_with_context(generate(body)),
            content_type="text/plain; charset=utf-8",
            headers=CORS_HEADERS,
        )
    except Exception as exc:
        traceback.print_exc()
        return Response(
            f"\u26a0\ufe0f Server error: {type(exc).__name__}: {exc}",
            status=200, content_type="text/plain; charset=utf-8", headers=CORS_HEADERS,
        )


@app.errorhandler(Exception)
def on_error(exc):
    traceback.print_exc()
    return Response(
        f"\u26a0\ufe0f Unexpected error: {type(exc).__name__}: {exc}",
        status=200, content_type="text/plain; charset=utf-8", headers=CORS_HEADERS,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
