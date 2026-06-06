import os
import httpx
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import JSONResponse

app = FastAPI()

# --- CONFIGURATION ---
# Replace these with values from your Meta Dashboard (Getting Started tab)
ACCESS_TOKEN = "EAAVam4Bnn98BRorLPXzUJTHMCAt2y6OfwS8OPQrHNozj3T8qhpTVmps5FQxDsRQiicrFKgt0HnbvVPSSiuQSjyFl4ZBRFTGmB3ytVxYpZBJfG8cKiZCgvPifdlxkZChfaVdTA5It3vX4loNUqCUa38CrZC2oUYOZBUbZCLZA5shGnZAc4t3P7F2IJqNjoDPYwpJP5922IcC9JieZCrgiFJSNcOT69fd0bOeil31N6BpDuVacik8IfRYUZAaUr0yKg0gk4ySWONQdlYaLZAdjkKQJNQZDZD"
PHONE_NUMBER_ID = "1171106572751707" # Copied from your payload logs
VERIFY_TOKEN = "AmitTest123456"

@app.get("/")
async def health():
    return {"status": "online"}

@app.get("/webhook")
async def verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return Response(content=str(hub_challenge), media_type="text/plain")
    return Response(content="Token Mismatch", status_code=403)

@app.post("/webhook")
async def handle_message(request: Request):
    payload = await request.json()
    
    try:
        # Navigate the JSON tree to find the message text and sender
        entry = payload["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        
        if "messages" in value:
            message = value["messages"][0]
            sender_id = message["from"]
            text_body = message["text"]["body"]
            
            print(f"📩 New Message from {sender_id}: {text_body}")

            # Send a response back
            await send_whatsapp_message(sender_id, f"Ciao Amit! I received your message: '{text_body}'")

    except Exception as e:
        print(f"❌ Error processing payload: {e}")

    return JSONResponse(content={"status": "success"}, status_code=200)

async def send_whatsapp_message(to_phone_number, message_text):
    """Sends a text message back to the user via WhatsApp API."""
    url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "text",
        "text": {"body": message_text}
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json=data)
        if response.status_code == 200:
            print(f"✅ Reply sent to {to_phone_number}")
        else:
            print(f"❌ Failed to send reply: {response.text}")
