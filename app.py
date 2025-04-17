import os
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Init Twilio + OpenAI
twilio_client = Client(os.getenv("TWILIO_SID"), os.getenv("TWILIO_AUTH"))
openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CALENDLY_LINK = os.getenv("CALENDLY_LINK")

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
        return ("", 200)
    except Exception as e:
        print("Twilio error:", e)
        return ("", 500)

@app.route("/sms-reply", methods=["POST"])
def sms_reply():
    user_msg = request.form.get("Body")
    from_number = request.form.get("From")

    prompt = f"""
    You are an assistant for a blue-collar business. Use the info below to answer questions.
    - Services: landscaping, snow removal, garden design, hardscaping
    - Area: Montreal & Laval
    - Booking: send this link if asked to book → {CALENDLY_LINK}
    - Hours: Mon–Sat 8am–6pm

    Customer says: "{user_msg}"
    """

    try:
        completion = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        reply = completion.choices[0].message.content
    except Exception as e:
        print("OpenAI error:", e)
        reply = "Sorry, something went wrong. We'll get back to you shortly."

    twiml = MessagingResponse()
    twiml.message(reply)
    return Response(str(twiml), mimetype="application/xml")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
