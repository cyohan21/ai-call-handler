from flask import Flask, request
import os
from openai import OpenAI
import telnyx
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
telnyx.api_key = os.getenv("TELNYX_API_KEY")


@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Altura AI Assistant is live.", 200

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    print("📩 RAW BODY:", request.data)
    print("📩 HEADERS:", dict(request.headers))
    try:
        data = request.get_json(force=True)
        print("📨 Parsed JSON:", data)
    except Exception as e:
        print("❌ JSON parse failed:", e)
        return "Bad JSON", 400

    payload = data.get("data", {}).get("payload", {})
    incoming_message = payload.get("text")
    from_number = payload.get("from")

    print("🧪 Debug: payload =", payload)
    print("🧪 text =", incoming_message)
    print("🧪 from =", from_number)

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
        print("🧠 About to call send_sms with:", from_number, reply)
        send_sms(from_number, reply)
    except Exception as e:
        print("❌ Telnyx send error:", str(e))
        return "Send failed", 500

    return "OK", 200

def send_sms(to_number, message):
    try:
        telnyx_number = os.getenv("TELNYX_NUMBER")

        print("📨 send_sms() called!")
        print("🔑 TELNYX_NUMBER:", telnyx_number)
        print("📞 To:", to_number)
        print("💬 Message:", message)

        if not telnyx_number:
            raise ValueError("TELNYX_NUMBER is missing from environment variables.")
        if not to_number:
            raise ValueError("Recipient phone number (to_number) is missing.")
        if not message:
            raise ValueError("Message content is empty.")

        response = telnyx.Message.create(
            from_=telnyx_number,
            to=to_number,
            text=message
        )

        print("✅ Telnyx message sent!")
        print("📤 Telnyx SDK Response:", response.to_dict())

    except Exception as e:
        print("❌ send_sms() FAILED:", str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)