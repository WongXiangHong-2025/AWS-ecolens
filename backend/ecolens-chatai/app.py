"""
EcoLens — ChatAI (chatbot widget).

Flask app running behind the AWS Lambda Web Adapter. Streams a chat reply
from Amazon Bedrock. Accepts the full conversation history so the assistant
remembers prior turns, plus the latest analysis outputs as grounding context.

Request body:
{
  "message": "latest user message",
  "history": [{"role": "user"|"assistant", "content": "..."}],
  "context": { "<widget title>": "<widget output text>", ... },  # optional
  "file_data": "<base64>",   # optional
  "file_mime": "image/png"   # optional
}
"""
import json
import os

import boto3
from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-5"))
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

SYSTEM_PROMPT = (
    "You are EcoLens ChatAI, a friendly sustainable packaging assistant for SMEs in "
    "Malaysia and Southeast Asia. Chat about anything the customer asks and provide the "
    "best recommendations based on the EcoLens analysis outputs supplied to you as "
    "context. Reference those outputs when relevant, and proactively ask the customer "
    "for any additional information you need to give a more precise recommendation. "
    "Keep a warm, practical, business-oriented tone."
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def build_request(body):
    system = SYSTEM_PROMPT

    context = body.get("context") or {}
    ctx_lines = [f"### {k}\n{v}" for k, v in context.items() if v]
    if ctx_lines:
        system += (
            "\n\nHere are the latest EcoLens analysis outputs for this product. "
            "Use them as the knowledge base for your answers:\n\n"
            + "\n\n".join(ctx_lines)
        )

    messages = []
    for turn in body.get("history") or []:
        role = turn.get("role")
        text = turn.get("content")
        if role in ("user", "assistant") and text:
            messages.append({"role": role, "content": [{"type": "text", "text": text}]})

    # Latest user message, optionally with an attached file.
    user_content = []
    file_data = body.get("file_data")
    file_mime = body.get("file_mime")
    if file_data and file_mime and file_mime.startswith("image/"):
        media_type = file_mime if file_mime != "image/jpg" else "image/jpeg"
        user_content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": file_data},
            }
        )
    user_content.append({"type": "text", "text": body.get("message") or ""})
    messages.append({"role": "user", "content": user_content})

    return {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "temperature": 0.6,
        "system": system,
        "messages": messages,
    }


def generate(body):
    req = build_request(body)
    try:
        response = bedrock.invoke_model_with_response_stream(
            modelId=MODEL_ID, body=json.dumps(req)
        )
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
