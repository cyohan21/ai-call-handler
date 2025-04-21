# telnyx-test.py

from dotenv import load_dotenv
load_dotenv()   # ← MUST come first, before any os.getenv()

import os
from flask import Flask, request
from openai import OpenAI
import telnyx

app = Flask(__name__)

# Now these pick up values from .env / Render’s environment
OPENAI_KEY  = os.getenv("OPENAI_API_KEY")
TELNYX_KEY  = os.getenv("TELNYX_API_KEY")
TELNYX_NUM  = os.getenv("TELNYX_NUMBER")

print("🔐 Loaded OPENAI_API_KEY:", bool(OPENAI_KEY))
print("🔐 Loaded TELNYX_API_KEY:", bool(TELNYX_KEY))
print("🔐 Loaded TELNYX_NUMBER:", TELNYX_NUM)

client = OpenAI(api_key=OPENAI_KEY)
telnyx.api_key = TELNYX_KEY

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Altura AI Assistant is live.", 200

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    print("📩 RAW BODY:", request.data)
    print("📩 HEADERS:", dict(request.headers))

    # Try JSON
    try:
        data = request.get_json(force=True)
        print("📨 Parsed JSON:", data)
    except Exception as e:
        print("❌ JSON parse failed:", e)
        return "Bad JSON", 400

    payload = data.get("data", {}).get("payload", {})
    text   = payload.get("text")
    sender = payload.get("from")

    print("🧪 payload keys:", list(payload.keys()))
    print("🧪 text:", text)
    print("🧪 from:", sender)

    if not text or not sender:
        print("⚠️ Missing text or sender")
        return "Missing data", 400

    # Generate AI reply
    try:
        resp = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role":"user","content": text}],
            temperature=0.7,
        )
        reply = resp.choices[0].message.content.strip()
        print("🤖 AI Reply:", reply)
    except Exception as e:
        print("❌ OpenAI error:", e)
        return "OpenAI error", 500

    # Send SMS
    print("🧠 Calling send_sms…")
    send_sms(sender, reply)
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
