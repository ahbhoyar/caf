import os
import logging
import requests
from fastapi import FastAPI, Request, Response, Query

# Configure clear logging format
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# Retrieve values from your Render Environment Variables
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "AmitTest123456")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

@app.get("/")
def read_root():
    logger.info("Health check endpoint hit via GET /")
    return {"status": "online", "message": "WhatsApp Webhook Server is live!"}

# --- 1. WEBHOOK VERIFICATION (GET HANDSHAKE) ---
from fastapi import Request, Response

@app.get("/webhook")
async def verify_webhook(request: Request):
    # Explicitly extract parameters using Meta's exact dot-notation keys
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")
    
    print(f"⚙️ Handshake Check -> Mode: {hub_mode} | Token: {hub_verify_token}")
    
    # Read the target verification token from your environment configuration
    import os
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "AmitTest123456")
    
    if hub_mode == "subscribe" and hub_verify_token == expected_token:
        print("✅ Handshake verification successful!")
        # Return the challenge value as plain text with a status 200
        return Response(content=hub_challenge, media_type="text/plain")
        
    print("❌ Handshake verification failed. Tokens do not match.")
    return Response(content="Verification token mismatch", status_code=403)

# --- 2. WEBHOOK PROCESSING (POST MESSAGES) ---
@app.post("/webhook")
async def process_webhook(request: Request):
    try:
        payload = await request.json()
        logger.info(f"📥 Received inbound event packet: {payload}")
        
        # Parse layout checks
        if "entry" in payload and payload["entry"]:
            entry = payload["entry"][0]
            if "changes" in entry and entry["changes"]:
                change = entry["changes"][0]
                value = change.get("value", {})
                
                # Verify that this packet contains a user text message
                if "messages" in value and value["messages"]:
                    message_obj = value["messages"][0]
                    from_number = message_obj.get("from")
                    phone_number_id = value.get("metadata", {}).get("phone_number_id")
                    
                    # Extract the body of the incoming text message
                    user_message = ""
                    if message_obj.get("type") == "text":
                        user_message = message_obj.get("text", {}).get("body", "")
                    
                    logger.info(f"💬 Found Message from {from_number}: '{user_message}'")
                    
                    # Construct a direct static response without using OpenAI
                    echo_response = f"Pipeline Test Successful! Your server captured the message: '{user_message}'"
                    
                    # Dispatch message back to user phone number via Graph API
                    if ACCESS_TOKEN and phone_number_id:
                        send_whatsapp_message(phone_number_id, from_number, echo_response)
                    else:
                        logger.warning("⚠️ Message not sent outbound. WHATSAPP_ACCESS_TOKEN or phone_number_id missing.")
                        
                elif "statuses" in value:
                    logger.info("📝 Log event ignored: Internal status/read receipt update packet.")
                    
    except Exception as e:
        logger.error(f"💥 Failed to parse incoming packet matrix: {str(e)}")
        
    return {"status": "success"}

def send_whatsapp_message(phone_number_id: str, recipient_number: str, text_body: str):
    url = f"https://graph.facebook.com/v17.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "text",
        "text": {"body": text_body}
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        logger.info(f"📡 Meta Send Response Code: {response.status_code} - Log Details: {response.text}")
    except Exception as e:
        logger.error(f"❌ Network dispatch error attempting to route outbound response: {e}")
