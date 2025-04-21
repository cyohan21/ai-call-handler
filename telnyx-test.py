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
    data = request.get_json()
    print("📨 Webhook payload:", data)  # <-- Log it to Render for debugging

    incoming_message = data.get("data", {}).get("payload", {}).get("text", "")
    from_number = data.get("data", {}).get("payload", {}).get("from", "")

    print("📩 Incoming message:", incoming_message)
    print("📱 From number:", from_number)

    if not incoming_message or not from_number:
        return "Missing message or number", 400

    # Generate AI response
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": incoming_message}],
        temperature=0.7,
    )
    reply = response.choices[0].message.content

    send_sms(from_number, reply)

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
    requests.post("https://api.telnyx.com/v2/messages", json=data, headers=headers)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)