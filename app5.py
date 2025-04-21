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
from gspread_formatting import format_cell_range, CellFormat, Color
from gspread.utils import a1_range_to_grid_range

def log_to_sheet_sorted(platform, handle, user_msg, ai_reply):
    try:
        # Setup auth
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name("google-credentials.json", scope)
        gclient = gspread.authorize(creds)
        sheet_file = gclient.open_by_key(os.getenv("SPREADSHEET_ID"))

        # Monthly sheet
        now = datetime.now()
        month_name = now.strftime("%B %Y")
        try:
            sheet = sheet_file.worksheet(month_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = sheet_file.add_worksheet(title=month_name, rows="1000", cols="4")

        today_str = now.strftime("%B %d %Y")
        timestamp = now.strftime("%Y-%m-%d %H:%M")

        # Check if today's section already exists
        col_values = sheet.col_values(1)
        if f"🟦 {today_str}" not in col_values:
            sheet.append_row([f"🟦 {today_str}", "", "", ""])
            section_row = len(sheet.get_all_values())

            # Format section header
            format_cell_range(sheet, f"A{section_row}:D{section_row}", CellFormat(
                backgroundColor=Color(0.7, 0.85, 1),  # light blue
                textFormat={"bold": True}
            ))

            sheet.append_row(["Date/Time", "Source", "Username/Handle", "Conversation"])
            format_cell_range(sheet, f"A{section_row+1}:D{section_row+1}", CellFormat(
                backgroundColor=Color(0.9, 0.9, 0.9),  # light gray
                textFormat={"bold": True}
            ))

        # Append logs
        sheet.append_row([timestamp, platform, handle, f"User: {user_msg}"])
        sheet.append_row([timestamp, platform, handle, f"AI: {ai_reply}"])

        # Sort entire data range by Date/Time (column A), descending
        values = sheet.get_all_values()
        headers = values[0]
        data_rows = values[1:]

        # Filter out section headers and blank rows
        data_rows = [row for row in data_rows if not row[0].startswith("🟦") and any(cell.strip() for cell in row)]

        # Sort by datetime descending
        sorted_data = sorted(data_rows, key=lambda r: r[0], reverse=True)

        # Rebuild sheet: clear and re-append
        sheet.clear()
        sheet.append_row(headers)
        for row in sorted_data:
            sheet.append_row(row)

    except Exception as e:
        print("❌ Error in sorted log_to_sheet:", e)


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
        reply = messages.data[0].content[0].text.value.strip()

        # Log conversation
        log_to_sheet_sorted("SMS", from_number, user_msg, reply)

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