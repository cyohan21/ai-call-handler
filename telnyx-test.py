# telnyx-test.py

from dotenv import load_dotenv
load_dotenv()   # Load .env before any getenv()

import os
from flask import Flask, request
from openai import OpenAI
import telnyx

app = Flask(__name__)

# Load environment variables
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
TELNYX_KEY = os.getenv("TELNYX_API_KEY")
TELNYX_NUM = os.getenv("TELNYX_NUMBER")

# Startup checks
print("🔐 OPENAI_API_KEY loaded?:", bool(OPENAI_KEY))
print("🔐 TELNYX_API_KEY loaded?:", bool(TELNYX_KEY))
print("🔐 TELNYX_NUMBER:", TELNYX_NUM)

# Initialize clients
client = OpenAI(api_key=OPENAI_KEY)
telnyx.api_key = TELNYX_KEY

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Altura AI Assistant is live.", 200

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    # Log raw request
    print("📩 RAW BODY:", request.data)
    print("📩 HEADERS:", dict(request.headers))

    # Parse JSON
    try:
        data = request.get_json(force=True)
        print("📨 Parsed JSON:", data)
    except Exception as e:
        print("❌ JSON parse failed:", e)
        return "Bad JSON", 400

    # Only handle inbound message received events
    event_type = data.get("data", {}).get("event_type")
    if event_type != "message.received":
        print("⏭ Skipping non-inbound event_type:", event_type)
        return "OK", 200

    payload = data["data"]["payload"]
    # Ensure payload direction is inbound
    if payload.get("direction") != "inbound":
        print("⏭ Skipping non-inbound payload direction:", payload.get("direction"))
        return "OK", 200

    # Extract message and sender
    incoming_message = payload.get("text")
    from_number      = payload.get("from", {}).get("phone_number")
    print("🧪 Incoming text:", incoming_message)
    print("🧪 From number:", from_number)

    if not incoming_message or not from_number:
        print("⚠️ Missing text or from_number")
        return "Missing data", 400

    # Call OpenAI Chat Completion (GPT-3.5 Turbo)
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content": incoming_message}]
        )
        reply = resp.choices[0].message.content.strip()
        print("🤖 AI Reply:", reply)
    except Exception as e:
        print("❌ OpenAI error:", e)
        return "OpenAI error", 500

    # Send SMS reply
    send_sms(from_number, reply)
    return "OK", 200


def send_sms(to_number, message):
    print("🧠 send_sms() called")
    print("📞 To:", to_number)
    print("💬 Message:", message)

    if not TELNYX_KEY or not TELNYX_NUM:
        print("❌ Missing TELNYX credentials")
        return

    try:
        res = telnyx.Message.create(
            from_=TELNYX_NUM,
            to=to_number,
            text=message
        )
        print("✅ Telnyx send response:", res.to_dict())
    except Exception as e:
        print("❌ send_sms error:", e)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
