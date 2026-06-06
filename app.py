import os
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import JSONResponse

app = FastAPI()

# Read the verification token dynamically (fallback to your hardcoded one if empty)
EXPECTED_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "AmitTest123456")

@app.get("/")
async def health_check():
    """
    Main system health check endpoint.
    Returns 200 OK to keep the Render container running.
    """
    return {"status": "healthy", "service": "WhatsApp Webhook Core"}


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    """
    Handles Meta's GET verification handshake using clean FastAPI Query aliases.
    """
    print(f"⚙️ Handshake Received -> Mode: {hub_mode} | Token: '{hub_verify_token}'")

    if hub_mode == "subscribe" and hub_verify_token == EXPECTED_TOKEN:
        print("✅ Handshake verification successful!")
        # Meta expects the raw integer/string challenge returned exactly as-is
        return Response(content=str(hub_challenge), media_type="text/plain")

    print(f"❌ Verification failed. Expected '{EXPECTED_TOKEN}', got '{hub_verify_token}'")
    return Response(content="Verification token mismatch", status_code=403)


@app.post("/webhook")
async def process_webhook(request: Request):
    """
    Handles incoming POST notifications containing real-time WhatsApp user text messages.
    """
    try:
        payload = await request.json()
        print(f"📥 Received inbound event packet: {payload}")
        
        # Safely extract messages from Meta's nested structure
        if "entry" in payload and payload["entry"]:
            entry_data = payload["entry"][0]
            if "changes" in entry_data and entry_data["changes"]:
                change_value = entry_data["changes"][0]["value"]
                
                if "messages" in change_value and change_value["messages"]:
                    message_object = change_value["messages"][0]
                    sender_phone = message_object.get("from")
                    message_text = message_object.get("text", {}).get("body", "")
                    
                    print(f"💬 Found Message from {sender_phone}: '{message_text}'")
                    
                    # 🚀 Add your messaging trigger logic here (e.g., calling OpenAI)
                    
        return JSONResponse(content={"status": "success"}, status_code=200)
        
    except Exception as e:
        print(f"❌ Error parsing POST webhook payload: {str(e)}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)
