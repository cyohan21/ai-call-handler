from flask import Flask, request
import os
from openai import OpenAI
import telnyx


app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Altura AI Assistant is live.", 200

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    try:
        data = request.get_json(force=True, silent=False)
        print("📨 Raw payload received:", data)
    except Exception as e:
        print("❌ Failed to parse JSON:", str(e))
        return "Invalid JSON", 400

    payload = data.get("data", {}).get("payload", {})
    incoming_message = payload.get("text")
    from_number = payload.get("from")

    print(f"📩 Message: {incoming_message}")
    print(f"📱 From: {from_number}")

    if not incoming_message or not from_number:
        print("⚠️ Missing text or sender in payload")
        return "Missing message or number", 400

    # AI response generation
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": incoming_message}],
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        print("🤖 AI Reply:", reply)
    except Exception as e:
        print("❌ OpenAI Error:", str(e))
        return "OpenAI failed", 500

    # Send SMS reply
    try:
        send_sms(from_number, reply)
    except Exception as e:
        print("❌ Telnyx send error:", str(e))
        return "Send failed", 500

    return "OK", 200

telnyx.api_key = os.getenv("TELNYX_API_KEY")

def send_sms(to_number, message):
    try:
        response = telnyx.Message.create(
            from_=os.getenv("TELNYX_NUMBER"),
            to=to_number,
            text=message
        )
        print("📤 Telnyx SDK Response:", response)
    except Exception as e:
        print("❌ Telnyx SDK Error:", str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)