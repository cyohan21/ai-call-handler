from flask import Flask, request
import os
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    incoming_message = request.form.get("text", "")
    from_number = request.form.get("from", "")

    # Generate AI response
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": incoming_message}],
        temperature=0.7,
    )
    reply = response.choices[0].message.content

    # Send reply using Telnyx
    send_sms(from_number, reply)

    return "", 200

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