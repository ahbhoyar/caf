import os
import sqlite3
import json
import requests
from fastapi import FastAPI, Request, Response, HTTPException

app = FastAPI()

# 1. READ ENVIRONMENT VARIABLES SAFELY WITH DEFAULT FALLBACKS
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
WA_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "")

DB_FILE = "./caf_state.db"

def init_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    phone TEXT PRIMARY KEY,
                    language TEXT,
                    current_step TEXT,
                    selected_service TEXT,
                    collected_data TEXT
                )
            """)
        print("✅ Database initialized successfully inside the project directory!")
    except Exception as e:
        print(f"❌ Critical Database Initialization Failure: {e}")

# Run database initializer safely
init_db()

def get_session(phone: str):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT language, current_step, selected_service, collected_data FROM sessions WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            if row:
                return {"language": row[0], "current_step": row[1], "selected_service": row[2], "collected_data": json.loads(row[3])}
    except Exception as e:
        print(f"⚠️ Error reading session from DB: {e}")
    return {"language": "", "current_step": "START", "selected_service": "", "collected_data": {}}

def save_session(phone: str, session: dict):
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sessions (phone, language, current_step, selected_service, collected_data)
                VALUES (?, ?, ?, ?, ?)
            """, (phone, session["language"], session["current_step"], session["selected_service"], json.dumps(session["collected_data"])))
    except Exception as e:
        print(f"⚠️ Error saving session to DB: {e}")

def think_and_reply(phone: str, user_msg: str) -> str:
    # Fallback response if OpenAI key is missing or invalid
    if not OPENAI_API_KEY:
        print("⚠️ Warning: OPENAI_API_KEY variable is empty!")
        return "Benvenuto al CAF. Scegli la lingua / Choose language:\n1. English\n2. Italiano"

    session = get_session(phone)
    system_prompt = f"""
    You are an autonomous Italian CAF Agency Assistant.
    Current state:
    - Language: {session['language'] if session['language'] else 'Not set'}
    - Step: {session['current_step']}
    - Service: {session['selected_service'] if session['selected_service'] else 'None'}
    
    GUIDELINES:
    1. If step is 'START', ask them politely to choose a language: '1. English\n2. Italiano'.
    2. Once language is selected, display the CAF menu: 1. Modello 730, 2. ISEE & Bonus, 3. Immigrazione, 4. Parla con un Operatore.
    3. If they select a service, ask them to type their document name or provide summary details.
    """

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}]
    }
    
    try:
        res = requests.post(url, json=payload, headers=headers)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
        else:
            print(f"⚠️ OpenAI returned status code {res.status_code}: {res.text}")
    except Exception as e:
        print(f"❌ OpenAI API Exception: {e}")
        
    return "Grazie. La tua richiesta è in elaborazione." if session["language"] == "it" else "Thank you. Your request is being processed."

@app.get("/")
def home_check():
    return {"status": "healthy", "service": "CAF Automation Engine"}

@app.get("/webhook")
def verify(request: Request):
    if request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=request.query_params.get("hub.challenge"))
    return HTTPException(status_code=403)

@app.post("/webhook")
async def handle_incoming(request: Request):
    try:
        payload = await request.json()
        print(f"📥 Received inbound event packet: {json.dumps(payload)}")
        
        entry = payload["entry"][0]["changes"][0]["value"]
        if "messages" in entry:
            msg_obj = entry["messages"][0]
            phone = msg_obj["from"]
            body_text = msg_obj.get("text", {}).get("body", "")
            
            metadata = entry.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id", "1171106572751707")
            
            # Generate the text reply
            reply = think_and_reply(phone, body_text)
            
            # Post reply message back to Meta WhatsApp v25.0 Gateway
            meta_url = f"https://graph.facebook.com/v25.0/{phone_number_id}/messages"
            headers = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
            
            res = requests.post(
                meta_url,
                headers=headers,
                json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": reply}}
            )
            print(f"📡 Meta Send Response: {res.status_code} - Log: {res.text}")
            
    except Exception as e:
        print(f"❌ Webhook Execution Crash: {e}")
        
    return {"status": "ok"}
