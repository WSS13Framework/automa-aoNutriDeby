import os
from twilio.rest import Client

client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

msg = client.messages.create(
    from_=os.getenv("TWILIO_FROM_NUMBER"),
    body="🧪 Teste Hermes — WSS+13 + DeepSeek + Twilio. Pipeline vivo.",
    to=os.getenv("TWILIO_TEST_NUMBER")
)

print(f"✅ SID: {msg.sid}")
print(f"   Status: {msg.status}")
