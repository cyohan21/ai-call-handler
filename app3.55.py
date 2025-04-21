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
CALENDLY_LINK = os.getenv("CALENDLY_LINK")

# In-memory thread tracking for demo
user_threads = {}

# Function to log or update conversation in monthly Google Sheet tab
def log_to_sheet(platform, handle, user_msg, ai_reply):
    print("🚨 log_to_sheet() was called")
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("google-credentials.json", scope)
        gclient = gspread.authorize(creds)
        sheet_file = gclient.open("AI Conversation Logs")

        # Determine current month sheet name
        month_name = datetime.now().strftime("%B %Y")

        try:
            sheet = sheet_file.worksheet(month_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = sheet_file.add_worksheet(title=month_name, rows="1000", cols="4")
            sheet.append_row(["Date/Time", "Source", "Username/Handle", "Conversation"])
        print("🔍 Connected to sheet:", sheet.title)
        print("🔍 Headers found:", sheet.row_values(1))

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        convo_entry = f"[{now}] User: {user_msg}\n[{now}] AI: {ai_reply}\n"

        # Check if user already exists in this month's sheet
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):  # account for header
            if str(row['Username/Handle']).strip().lower() == str(handle).strip().lower() and \
   str(row['Source']).strip().lower() == str(platform).strip().lower():
                existing_text = sheet.cell(idx, 4).value or ""
                sheet.update_cell(idx, 4, existing_text + convo_entry)
                return

        # New conversation
        sheet.append_row([now, platform, handle, convo_entry])
    except Exception as e:
        print("❌ Error logging to Google Sheets:", e)
        raise

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
        if from_number in user_threads:
            thread_id = user_threads[from_number]
        else:
            thread = client.beta.threads.create()
            thread_id = thread.id
            user_threads[from_number] = thread_id

        client.beta.threads.messages.create(
            thread_id = thread_id,
            role="user",
            content=user_msg
        )
        run = client.beta.threads.runs.create(
            thread_id = thread_id,
            assistant_id=ASSISTANT_ID
        )
        while True:
            run_status = client.beta.threads.runs.retrieve(
                thread_id = thread_id,
                run_id=run.id
            )
            if run_status.status == "completed":
                break
            elif run_status.status in ["failed", "cancelled"]:
                raise Exception(f"Run failed with status: {run_status.status}")
            time.sleep(1)

        messages = client.beta.threads.messages.list(thread_id = thread_id)
        reply = messages.data[-1].content[0].text.value.strip()
        print("🤖 AI reply generated:", reply) 

        # Log conversation
        log_to_sheet("SMS", from_number, user_msg, reply)
        print("📄 log_to_sheet() was triggered.") 

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