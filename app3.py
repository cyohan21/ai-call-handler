import os
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
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
CALENDLY_LINK = os.getenv("CALENDLY_LINK")

# Function to log or update conversation in monthly Google Sheet tab
def log_to_sheet(platform, handle, user_msg, ai_reply):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("google-credentials.json", scope)
        client = gspread.authorize(creds)
        sheet_file = client.open("AI Conversation Logs")

        # Determine current month sheet name
        month_name = datetime.now().strftime("%B %Y")

        try:
            sheet = sheet_file.worksheet(month_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = sheet_file.add_worksheet(title=month_name, rows="1000", cols="4")
            sheet.append_row(["Date/Time", "Source", "Username/Handle", "Conversation"])

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        convo_entry = f"[{now}] User: {user_msg}\n[{now}] AI: {ai_reply}\n"

        # Check if user already exists in this month's sheet
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):  # account for header
            if row['Username/Handle'] == handle and row['Source'] == platform:
                existing_text = sheet.cell(idx, 4).value or ""
                sheet.update_cell(idx, 4, existing_text + convo_entry)
                return

        # New conversation
        sheet.append_row([now, platform, handle, convo_entry])
    except Exception as e:
        print("❌ Error logging to Google Sheets:", e)

@app.route("/sms-reply", methods=["POST"])
def sms_reply():
    from_number = request.form.get("From")
    user_msg = request.form.get("Body")
    twiml = MessagingResponse()

    system_msg = f"""
You are a helpful assistant for a blue-collar business.
Services include landscaping, concrete, retaining walls, and more.
Always reply professionally and helpfully. If someone asks to book, give them this link: {CALENDLY_LINK}
    """

    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ]
        )
        reply = completion.choices[0].message.content.strip()
        twiml.message(reply)

        # Log to Google Sheets in monthly tab
        log_to_sheet("SMS", from_number, user_msg, reply)

    except Exception as e:
        print("❌ GPT error:", e)
        twiml.message("Sorry, we're experiencing technical difficulties. Please try again later.")

    return Response(str(twiml), mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
