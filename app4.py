import os
import time
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Load environment variables
load_dotenv()
print("✅ OpenAI KEY LOADED:", os.getenv("OPENAI_API_KEY")[:10])

# Flask app
app = Flask(__name__)

# Init Twilio + OpenAI
twilio_client = Client(os.getenv("TWILIO_SID"), os.getenv("TWILIO_AUTH"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")

# In-memory thread mapping for conversational memory
user_threads = {}

# Function to log conversation in monthly Google Sheet tab
def log_to_sheet(platform, handle, user_msg, ai_reply):
    try:
        # — auth
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            "google-credentials.json", scope
        )
        gclient = gspread.authorize(creds)
        sheet_file = gclient.open_by_key(os.getenv("SPREADSHEET_ID"))

        # — ensure monthly tab
        month_name = datetime.now().strftime("%B %Y")
        try:
            sheet = sheet_file.worksheet(month_name)
            print(f"🔍 Found sheet tab '{month_name}'")
        except gspread.exceptions.WorksheetNotFound:
            print(f"➕ Creating sheet tab '{month_name}'")
            sheet = sheet_file.add_worksheet(
                title=month_name, rows="1000", cols="4"
            )
            sheet.append_row([
                "Date/Time", "Source", "Username/Handle", "Conversation"
            ])

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # — fetch all existing handles in col C (skip header)
        raw_handles = sheet.col_values(3)[1:]
        normalized = {h.strip().lower() for h in raw_handles if h}

        # — if first time for this handle, add a section header
        key = handle.strip().lower()
        if key not in normalized:
            print(f"🆕 First time for {handle}, inserting section header")
            sheet.append_row([now, platform, handle, f"🟢 New conversation with {handle}"])
        else:
            print(f"↪️ Existing conversation for {handle}")

        # — append each turn as its own row
        sheet.append_row([now, platform, handle, f"User: {user_msg}"])
        print(f"✏️ Logged USER message for {handle}")
        sheet.append_row([now, platform, handle, f"AI: {ai_reply}"])
        print(f"✏️ Logged AI reply for {handle}")

    except Exception as e:
        print("❌ Error logging to Google Sheets:", e)
        # swallow so SMS still goes through

@app.route("/sms-reply", methods=["POST"])
def sms_reply():
    user_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "").strip()

    if not user_msg:
        print("Empty or missing user message.")
        reply = "Sorry, we couldn't understand your message. Please try again."
        twiml = MessagingResponse()
        twiml.message(reply)
        return Response(str(twiml), mimetype="application/xml")

    print("📩 Message received:", user_msg)

    try:
        # conversational memory: reuse or create thread per user
        if from_number in user_threads:
            thread_id = user_threads[from_number]
            print(f"↪️ Continuing thread for {from_number}: {thread_id}")
        else:
            thread = client.beta.threads.create()
            thread_id = thread.id
            user_threads[from_number] = thread_id
            print(f"🆕 Created thread for {from_number}: {thread_id}")

        # send user message to thread
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=user_msg
        )
        # run assistant
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )
        # wait for completion
        while True:
            run_status = client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run_status.status == "completed":
                break
            elif run_status.status in ["failed", "cancelled"]:
                raise Exception(f"Run failed: {run_status.status}")
            time.sleep(1)

        # fetch messages and get latest assistant reply
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        # find last assistant message
        reply = None
        for msg in reversed(messages.data):
            if msg.role == "assistant":
                for part in msg.content:
                    if getattr(part, 'type', '') == "text":
                        reply = part.text.value.strip()
                        break
            if reply:
                break
        if not reply:
            raise Exception("No assistant reply found.")
        print("🤖 AI reply generated:", reply)

        # log conversation
        log_to_sheet("SMS", from_number, user_msg, reply)

    except Exception as e:
        print("❌ OpenAI error:", e)
        reply = "Sorry, something went wrong. We'll get back to you shortly."

    twiml = MessagingResponse()
    twiml.message(reply)
    return Response(str(twiml), mimetype="application/xml")

@app.route("/missed-call", methods=["POST"])
def missed_call():
    from_number = request.form.get("From")
    message = "Hey! Sorry we missed your call. How can we help you today?"
    try:
        twilio_client.messages.create(
            body=message,
            from_=os.getenv("TWILIO_NUMBER"),
            to=from_number
        )
    except Exception as e:
        print("Twilio error:", e)

    response = VoiceResponse()
    response.say("Thank you for calling. We’ll text you shortly.", voice="alice")
    return Response(str(response), mimetype="application/xml")

@app.route("/voice", methods=["POST"])
def voice():
    response = VoiceResponse()
    response.say("Please hold while we connect your call.", voice="alice")

    forward_to = os.getenv("FORWARD_TO_NUMBER")
    if forward_to:
        response.dial(forward_to)
    else:
        response.say("Sorry, we’re currently unavailable to take your call.")

    return Response(str(response), mimetype="application/xml")

@app.route("/handle-recording", methods=["POST"])
def handle_recording():
    recording_url = request.form.get("RecordingUrl")
    caller = request.form.get("From")

    try:
        twilio_client.messages.create(
            body=f"Voicemail from {caller}: {recording_url}",
            from_=os.getenv("TWILIO_NUMBER"),
            to=os.getenv("OWNER_NUMBER")
        )
    except Exception as e:
        print("Voicemail alert error:", e)

    return ("", 200)

@app.route("/call-status", methods=["POST"])
def call_status():
    call_status = request.form.get("CallStatus")
    from_number = request.form.get("From")

    if call_status in ["no-answer", "busy", "failed", "canceled"]:
        try:
            twilio_client.messages.create(
                body="We noticed you called but didn’t get through. Can we help?",
                from_=os.getenv("TWILIO_NUMBER"),
                to=from_number
            )
        except Exception as e:
            print("Early hangup SMS error:", e)

    return ("", 200)

@app.route("/test-gpt", methods=["GET"])
def test_gpt():
    try:
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content="Say hi in 3 words"
        )
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )
        while True:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if run_status.status == "completed":
                break
            time.sleep(1)
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        return messages.data[0].content[0].text.value.strip(), 200
    except Exception as e:
        print("❌ GPT ERROR:", e)
        return f"GPT error: {e}", 500

@app.route("/", methods=["GET"])
def home():
    return "AI Call Handler backend is running. Nothing to see here.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
