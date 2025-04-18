import os
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
print("✅ OpenAI KEY LOADED:", os.getenv("OPENAI_API_KEY")[:10])

app = Flask(__name__)

# Init Twilio + OpenAI
twilio_client = Client(os.getenv("TWILIO_SID"), os.getenv("TWILIO_AUTH"))
OpenAI.api_key = os.getenv("OPENAI_API_KEY")
CALENDLY_LINK = os.getenv("CALENDLY_LINK")

@app.route("/missed-call", methods=["POST"])
def missed_call():
    from_number = request.form.get("From")
    message = "Hey! Sorry we missed your call. How can we help you today?"

    # Send SMS to caller
    try:
        twilio_client.messages.create(
            body=message,
            from_=os.getenv("TWILIO_NUMBER"),
            to=from_number
        )
    except Exception as e:
        print("Twilio error:", e)

    # FIX: Return valid voice TwiML to avoid application error
    response = VoiceResponse()
    response.say("Thank you for calling. We’ll text you shortly.", voice="alice")
    return Response(str(response), mimetype="application/xml")

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

    calendly_link = CALENDLY_LINK or "https://calendly.com/caleb-yohannes2003"

    prompt = f"""
You are an assistant for a blue-collar business. Use the info below to answer questions.
- Services: landscaping, snow removal, garden design, hardscaping
- Area: Montreal & Laval
- Booking: send this link if asked to book → {calendly_link}
- Hours: Mon–Sat 8am–6pm

Customer says: "{user_msg}"
"""

    print("Prompt being sent to GPT:\n", prompt)

    try:
        completion = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        reply = completion.choices[0].message.content.strip()
    except Exception as e:
        print("OpenAI error:", e)
        reply = "Sorry, something went wrong. We'll get back to you shortly."

    twiml = MessagingResponse()
    twiml.message(reply)
    return Response(str(twiml), mimetype="application/xml")

# Call bridging from twilio number to the owner's number
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

# Sends voicemails to the owner via SMS
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


# Handles early hangups before timeout
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

    
@app.route("/", methods=["GET"])
def home():
    return "AI Call Handler backend is running. Nothing to see here.", 200
    
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
