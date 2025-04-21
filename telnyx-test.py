# telnyx-test.py

from dotenv import load_dotenv
load_dotenv()   # ← load .env before any getenv()

import os
from flask import Flask, request
from openai import OpenAI
import telnyx

app = Flask(__name__)

# Load your keys/IDs from the environment
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
OPENAI_KEY         = os.getenv("OPENAI_API_KEY")
TELNYX_KEY         = os.getenv("TELNYX_API_KEY")
TELNYX_NUM         = os.getenv("TELNYX_NUMBER")

# Startup checks
print("🔐 OPENAI_ASSISTANT_ID:", bool(OPENAI_ASSISTANT_ID), OPENAI_ASSISTANT_ID)
print("🔐 OPENAI_API_KEY loaded?:", bool(OPENAI_KEY))
print("🔐 TELNYX_API_KEY loaded?:", bool(TELNYX_KEY))
print("🔐 TELNYX_NUMBER:", TELNYX_NUM)

# Initialize clients
client        = OpenAI(api_key=OPENAI_KEY)
telnyx.api_key = TELNYX_KEY

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Altura AI Assistant is live.", 200

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    # Log raw request
    print("📩 RAW BODY:", request.data)
    print("📩 HEADERS:", dict(request.headers))

    # Parse JSON payload
    try:
        data = request.get_json(force=True)
        print("📨 Parsed JSON:", data)
    except Exception as e:
        print("❌ JSON parse failed:", e)
        return "Bad JSON", 400

    # Only handle inbound messages
    event_type = data.get("data", {}).get("event_type")
    if event_type != "message.received":
        print("⏭ Skipping non-inbound event:", event_type)
        return "OK", 200

    # Extract payload details
    payload = data.get("data", {}).get("payload", {})
    incoming_message = payload.get("text")
    from_number      = payload.get("from", {}).get("phone_number")

    print("🧪 text:", incoming_message)
    print("🧪 from (phone_number):", from_number)

    if not incoming_message or not from_number:
        print("⚠️ Missing text or sender in payload")
        return "Missing data", 400

    # Call your OpenAI custom assistant
    try:
        resp = client.chat.completions.create(
            assistant_id=OPENAI_ASSISTANT_ID,
            messages=[{"role":"user","content": incoming_message}]
        )
        reply = resp.choices[0].message.content.strip()
        print("🤖 AI Reply:", reply)
    except Exception as e:
        print("❌ OpenAI error:", e)
        return "OpenAI error", 500

    # Send the SMS reply
    print("🧠 Calling send_sms()…")
    send_sms(from_number, reply)
    return "OK", 200


def send_sms(to_number, message):
    print("📨 send_sms() called")
    print("🔑 TELNYX_NUMBER:", TELNYX_NUM)
    print("📞 To:", to_number)
    print("💬 Message:", message)

    if not TELNYX_KEY:
        print("❌ Missing TELNYX_API_KEY")
        return
    if not TELNYX_NUM:
        print("❌ Missing TELNYX_NUMBER")
        return

    try:
        res = telnyx.Message.create(
            from_=TELNYX_NUM,
            to=to_number,
            text=message
        )
        print("✅ Telnyx send response:", res.to_dict())
    except Exception as e:
        print("❌ send_sms() error:", e)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
