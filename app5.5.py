import os
import time
import re
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Dial, Connect
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

# Safe calculator

def safe_calculate(expression):
    try:
        cleaned = re.sub(r"[^0-9\.\+\-\*/\(\)\sx]", "", expression)
        return eval(cleaned, {"__builtins__": {}})
    except Exception as e:
        return f"Could not calculate: {e}"

# Tool definition for OpenAI
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "safe_calculate",
            "description": "Safely calculate a math expression like '100 * 20'",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate"
                    }
                },
                "required": ["expression"]
            }
        }
    }
]

# Log conversation to Sheets
def log_to_sheet(platform, handle, user_msg, ai_reply):
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name("google-credentials.json", scope)
        gclient = gspread.authorize(creds)
        sheet_file = gclient.open_by_key(os.getenv("SPREADSHEET_ID"))
        month_name = datetime.now().strftime("%B %Y")

        try:
            sheet = sheet_file.worksheet(month_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = sheet_file.add_worksheet(title=month_name, rows="1000", cols="4")
            sheet.append_row(["Date/Time", "Source", "Username/Handle", "Conversation"])

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        raw_handles = sheet.col_values(3)[1:]
        normalized = {h.strip().lower() for h in raw_handles if h}
        key = handle.strip().lower()
        if key not in normalized:
            sheet.append_row([now, platform, handle, f"🟢 New conversation with {handle}"])

        sheet.append_row([now, platform, handle, f"User: {user_msg}"])
        sheet.append_row([now, platform, handle, f"AI: {ai_reply}"])

    except Exception as e:
        print("❌ Error logging to Google Sheets:", e)

@app.route("/incoming-call", methods=["POST"])
def incoming_call():
    resp = VoiceResponse()
    resp.say("Please wait while we connect you to our assistant.")
    # after 20 seconds of no media / failure, Twilio will POST to /missed-call
    dial = Dial(action="/missed-call", timeout=20)  
    connect = Connect()
    connect.stream(url=f"wss://{request.url.hostname}/media-stream")
    dial.append(connect)
    resp.append(dial)
    return Response(str(resp), mimetype="application/xml")

@app.route("/missed-call", methods=["POST"])
def missed_call():
    from_number = request.form.get("From")
    status      = request.form.get("CallStatus") or request.form.get("DialCallStatus")
    if status in ("busy", "no-answer", "failed"):
        try:
            twilio_client.messages.create(
                body=   "Hey! Sorry we missed your call. How can we help today?",
                from_=  os.getenv("TWILIO_NUMBER"),
                to=     from_number
            )
        except Exception as e:
            app.logger.error("Twilio SMS send failed: %s", e)
    return ("", 204)


# SMS handling
@app.route("/sms-reply", methods=["POST"])
def sms_reply():
    user_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "").strip()

    if not user_msg:
        reply = "Sorry, we couldn't understand your message. Please try again."
        twiml = MessagingResponse()
        twiml.message(reply)
        return Response(str(twiml), mimetype="application/xml")

    try:
        thread_id = user_threads.get(from_number)
        if not thread_id:
            thread = client.beta.threads.create()
            thread_id = thread.id
            user_threads[from_number] = thread_id

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=user_msg)
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ASSISTANT_ID, tools=TOOLS)

        while True:
            run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)

            if run_status.status == "completed":
                break
            elif run_status.status == "requires_action":
                for tool_call in run_status.required_action.submit_tool_outputs.tool_calls:
                    expr = eval(tool_call.function.arguments).get("expression", "")
                    result = safe_calculate(expr)
                    client.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run.id,
                        tool_outputs=[{"tool_call_id": tool_call.id, "output": str(result)}]
                    )
            elif run_status.status in ["failed", "cancelled"]:
                raise Exception(f"Run failed with status: {run_status.status}")
            time.sleep(1)

        messages = client.beta.threads.messages.list(thread_id=thread_id)
        reply = messages.data[0].content[0].text.value.strip()

        log_to_sheet("SMS", from_number, user_msg, reply)

    except Exception as e:
        print("❌ OpenAI error:", e)
        reply = "Sorry, something went wrong. We'll get back to you shortly."

    twiml = MessagingResponse()
    twiml.message(reply)
    return Response(str(twiml), mimetype="application/xml")

# Remaining endpoints below are unchanged...
# (missed-call, voice, handle-recording, call-status, test-gpt, home)
# You can copy/paste them from your current file if needed

@app.route("/", methods=["GET"])
def home():
    return "AI Call Handler with Calculator Tool is running.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)