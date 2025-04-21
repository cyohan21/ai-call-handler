from flask import Flask, request
import os
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Altura AI Assistant is live.", 200

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    try:
        data = request.get_json(force=True) or {}
    except Exception as e:
        print("❌ Failed to parse JSON:", str(e))
        return "Invalid JSON", 400

    print("📨 Webhook payload:", data)

    payload = data.get("data", {}).get("payload", {})
    incoming_message = payload.get("text", "")
    from_number = payload.get("from", "")

    print(f"📩 Message: {incoming_message}")
    print(f"📱 From: {from_number}")

    if not incoming_message or not from_number:
        return "Missing message or number", 400

    # Test OpenAI call
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": incoming_message}],
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        print("🤖 AI Reply:", reply)
    except Exception as e:
        print("❌ OpenAI error:", str(e))
        return "OpenAI failed", 500

    try:
        send_sms(from_number, reply)
    except Exception as e:
        print("❌ Telnyx send error:", str(e))
        return "Send failed", 500

    return "OK", 200
def send_sms(to_number, message):
    import requests
    headers = {
        "Authorization": f"Bearer {os.getenv('TELNYX_API_KEY')}",
        "Content-Type": "application/json"
    }
    data = {
        "from": os.getenv("TELNYX_NUMBER"),
        "to": to_number,
        "text": message
    }
    r = requests.post("https://api.telnyx.com/v2/messages", json=data, headers=headers)
    print("📤 Telnyx Response:", r.status_code, r.text)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)