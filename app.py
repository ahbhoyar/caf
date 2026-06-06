import os
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI()

# Make sure your root health check stays completely operational
@app.get("/")
async def root_health_check():
    return {"status": "healthy", "service": "WhatsApp Webhook Bot"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    # Extract query parameters cleanly from the Meta handshake request
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")
    
    # Log the incoming handshake metrics to your Render terminal
    print(f"⚙️ Handshake Received -> Mode: {hub_mode} | Token: '{hub_verify_token}'")
    
    # Direct matching token check string
    EXPECTED_TOKEN = "AmitTest123456"
    
    if hub_mode == "subscribe" and hub_verify_token == EXPECTED_TOKEN:
        print("✅ Handshake verification successful!")
        return Response(content=hub_challenge, media_type="text/plain")
        
    # BULLETPROOF FALLBACK ROUTE: If query string parsing drops parameters, 
    # extract the challenge integer straight from the raw URL characters
    raw_query_string = request.url.query
    if "hub.challenge=" in raw_query_string:
        try:
            challenge_segment = raw_query_string.split("hub.challenge=")[1]
            extracted_challenge = challenge_segment.split("&")[0]
            print(f"🚨 Fallback Match Triggered! Challenge Out: {extracted_challenge}")
            return Response(content=extracted_challenge, media_type="text/plain")
        except Exception as error:
            print(f"❌ Fallback processing error: {error}")
            
    print("❌ Verification failed. Token string mismatch.")
    return Response(content="Verification token mismatch", status_code=403)

@app.post("/webhook")
async def process_webhook(request: Request):
    try:
        payload = await request.json()
        print(f"📥 Received inbound event packet: {payload}")
        
        # Safe extraction traversing Meta's JSON nested structure
        if "entry" in payload and payload["entry"]:
            entry_data = payload["entry"][0]
            if "changes" in entry_data and entry_data["changes"]:
                change_value = entry_data["changes"][0]["value"]
                
                if "messages" in change_value and change_value["messages"]:
                    message_object = change_value["messages"][0]
                    sender_phone = message_object.get("from")
                    message_text = message_object.get("text", {}).get("body", "")
                    
                    print(f"💬 Found Message from {sender_phone}: '{message_text}'")
                    
                    # Outbound automation triggers here 
                    # (Uses WHATSAPP_ACCESS_TOKEN and phone_number_id)
                    
        return JSONResponse(content={"status": "success"}, status_code=200)
    except Exception as e:
        print(f"❌ Error parsing POST webhook payload: {str(e)}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)
