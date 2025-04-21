from dotenv import load_dotenv
load_dotenv()  # Load .env before accessing any environment variables

import os
import time
from flask import Flask, request
from openai import OpenAI
import telnyx
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# Load env vars
OPENAI_KEY      = os.getenv("OPENAI_API_KEY")
TELNYX_KEY      = os.getenv("TELNYX_API_KEY")
TELNYX_NUM      = os.getenv("TELNYX_NUMBER")
ASSISTANT_ID    = os.getenv("OPENAI_ASSISTANT_ID")
GOOGLE_CREDS    = os.getenv("GOOGLE_CREDENTIALS_JSON", "google-credentials.json")

# Initialize clients
client = OpenAI(api_key=OPENAI_KEY)
telnyx.api_key = TELNYX_KEY

# Initialize Flask app\ app = Flask(__name__)
app = Flask(__name__)

# In-memory conversation threads
user_threads = {}

# Setup Google Sheets logging
def log_to_sheet(platform, handle, user_msg, ai_reply):
    try:
        scope = [
            "https://spreadsheets.google.com/feeds", 
            "https://www.googleapis.com/auth/drive"
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS, scope)
        gclient = gspread.authorize(creds)
        sheet_file = gclient.open("AI Conversation Logs")

        month_name = datetime.now().strftime("%B %Y")
        try:
            sheet = sheet_file.worksheet(month_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = sheet_file.add_worksheet(title=month_name, rows="1000", cols="4")
            sheet.append_row(["Date/Time", "Source", "Username/Handle", "Conversation"])

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        convo_entry = f"[{now}] User: {user_msg}\n[{now}] AI: {ai_reply}\n"
        # append or update existing
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):
            if row.get('Username/Handle','').strip().lower() == handle.strip().lower() and \
               row.get('Source','').strip().lower() == platform.strip().lower():
                existing = sheet.cell(idx, 4).value or ""
                sheet.update_cell(idx, 4, existing + convo_entry)
                return
        sheet.append_row([now, platform, handle, convo_entry])
    except Exception as e:
        print("❌ Error logging to Google Sheets:", e)

@app.route("/sms-handler", methods=["POST"])
def sms_handler():
    data = request.get_json(force=True)
    event = data.get("data", {})
    # Only inbound messages
    if event.get("event_type") != "message.received":
        return "OK", 200
    payload = event.get("payload", {})
    if payload.get("direction") != "inbound":
        return "OK", 200

    incoming = payload.get("text")
    from_info = payload.get("from", {})
    from_number = from_info.get("phone_number")
    if not incoming or not from_number:
        return "Missing data", 400

    try:
        # Manage thread
        if from_number in user_threads:
            thread_id = user_threads[from_number]
        else:
            thread = client.beta.threads.create()
            thread_id = thread.id
            user_threads[from_number] = thread_id
        # Send user message
        client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=incoming
        )
        # Run assistant
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )
        # Poll
        while True:
            status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if status.status == "completed":
                break
            if status.status in ["failed","cancelled"]:
                raise Exception(f"Run failed: {status.status}")
            time.sleep(1)
        # Get reply
        msgs = client.beta.threads.messages.list(thread_id=thread_id)
        ai_reply = msgs.data[0].content[0].text.value.strip()
        print("🤖 AI Reply:", ai_reply)
        # Log chat
        log_to_sheet("SMS", from_number, incoming, ai_reply)
    except Exception as e:
        print("❌ OpenAI error:", e)
        ai_reply = "Sorry, something went wrong generating your response."
    # Send via Telnyx
    send_sms(from_number, ai_reply)
    return "OK", 200


def send_sms(to_number, message):
    if not TELNYX_NUM or not TELNYX_KEY:
        print("❌ Missing Telnyx config")
        return
    try:
        res = telnyx.Message.create(
            from_=TELNYX_NUM,
            to=to_number,
            text=message
        )
        print("✅ Sent SMS:", res.to_dict())
    except Exception as e:
        print("❌ send_sms error:", e)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
