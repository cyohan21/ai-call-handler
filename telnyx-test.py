# telnyx-test.py

from dotenv import load_dotenv
load_dotenv()   # Load .env before any getenv()

import os
from flask import Flask, request
from openai import OpenAI
import telnyx
import time

app = Flask(__name__)

# Load environment variables
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
TELNYX_KEY = os.getenv("TELNYX_API_KEY")
TELNYX_NUM = os.getenv("TELNYX_NUMBER")
# Load the Assistant ID so we can target a specific fine-tuned or custom assistant
ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")

# Initialize clients
client = OpenAI(api_key=OPENAI_KEY)
telnyx.api_key = TELNYX_KEY

@app.route("/", methods=["GET", "HEAD"])
def home():
    return "Altura AI Assistant is live.", 200

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    # Log raw request for debugging
    print("📩 RAW BODY:", request.data)
    print("📩 HEADERS:", dict(request.headers))

    # Parse JSON
    try:
        data = request.get_json(force=True)
        print("📨 Parsed JSON:", data)
    except Exception as e:
        print("❌ JSON parse failed:", e)
        return "Bad JSON", 400

    event_type = data.get("data", {}).get("event_type")
    if event_type != "message.received":
        print("⏭ Skipping non-inbound event_type:", event_type)
        return "OK", 200

    payload = data["data"]["payload"]
    if payload.get("direction") != "inbound":
        print("⏭ Skipping non-inbound payload direction:", payload.get("direction"))
        return "OK", 200

    incoming_message = payload.get("text")
    from_number      = payload.get("from", {}).get("phone_number")
    if not incoming_message or not from_number:
        print("⚠️ Missing text or from_number")
        return "Missing data", 400

    print("🧪 Incoming text:", incoming_message)
    print("🧪 From number:", from_number)

    # Generate AI reply using beta threads + assistant_id
    try:
        # Create a new thread and send the user message
        thread = client.beta.threads.create()
        thread_id = thread.id
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=incoming_message
        )

        # Run the assistant
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )

        # Poll until complete
        while True:
            status = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if status.status == "completed":
                break
            if status.status in ["failed", "cancelled"]:
                raise Exception(f"Run failed: {status.status}")
            time.sleep(1)

        # Retrieve the assistant's reply
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        reply = messages.data[0].content[0].text.value.strip()
        print("🤖 AI Reply:", reply)

    except Exception as e:
        print("❌ OpenAI error:", e)
        reply = "Sorry, something went wrong generating that response."

    # Send SMS via Telnyx
    send_sms(from_number, reply)
    return "OK", 200


def send_sms(to_number, message):
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
