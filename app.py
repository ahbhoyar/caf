import os
import sqlite3
import json
import requests
from fastapi import FastAPI, Request, Response, HTTPException
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = FastAPI()

# 1. READ CLOUD ENVIRONMENT VARIABLES
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WA_TOKEN = os.getenv("WHATSAPP_API_TOKEN")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")

# Render persistent disk mount path
DB_FILE = "/data/caf_state.db"

def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
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
init_db()

def get_session(phone: str):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT language, current_step, selected_service, collected_data FROM sessions WHERE phone = ?", (phone,))
        row = cursor.fetchone()
        if row:
            return {"language": row[0], "current_step": row[1], "selected_service": row[2], "collected_data": json.loads(row[3])}
        return {"language": "", "current_step": "START", "selected_service": "", "collected_data": {}}

def save_session(phone: str, session: dict):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO sessions (phone, language, current_step, selected_service, collected_data)
            VALUES (?, ?, ?, ?, ?)
        """, (phone, session["language"], session["current_step"], session["selected_service"], json.dumps(session["collected_data"])))

def sync_to_google_sheet(phone: str, service: str, lang: str, notes: str):
    try:
        creds_json = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON", "{}"))
        if not creds_json: return
        creds = Credentials.from_service_account_info(creds_json, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        service_sheet = build('sheets', 'v4', credentials=creds)
        
        values = [[phone, service, lang, notes, "Pending Operator Review"]]
        body = {'values': values}
        service_sheet.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, range="Sheet1!A:E",
            valueInputOption="USER_ENTERED", body=body
        ).execute()
    except Exception as e:
        print(f"Sheet Sync Error: {e}")

def think_and_reply(phone: str, user_msg: str) -> str:
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
    4. When they provide it, acknowledge receipt, tell them it is saved, and end the loop.
    """

    tools = [{
        "type": "function",
        "function": {
            "name": "update_customer_state",
            "description": "Updates database flags dynamically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "enum": ["en", "it"]},
                    "current_step": {"type": "string", "enum": ["START", "MENU", "COLLECTING", "COMPLETE"]},
                    "selected_service": {"type": "string"},
                    "trigger_google_sync": {"type": "boolean"},
                    "notes": {"type": "string"}
                },
                "required": ["current_step"]
            }
        }
    }]

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_msg}],
        "tools": tools,
        "tool_choice": "auto"
    }
    
    response = requests.post(url, json=payload, headers=headers).json()
    choice = response['choices'][0]['message']
    bot_reply = choice.get("content", "")
    
    if choice.get("tool_calls"):
        args = json.loads(choice["tool_calls"][0]["function"]["arguments"])
        if "language" in args: session["language"] = args["language"]
        if "selected_service" in args: session["selected_service"] = args["selected_service"]
        session["current_step"] = args["current_step"]
        
        if args.get("trigger_google_sync"):
            sync_to_google_sheet(phone, session["selected_service"], session["language"], args.get("notes", "Data received"))
            
        save_session(phone, session)
        
    if not bot_reply:
        bot_reply = "Grazie. Pratica registrata." if session["language"] == "it" else "Thank you. Service logged."
    return bot_reply

@app.get("/webhook")
def verify(request: Request):
    if request.query_params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=request.query_params.get("hub.challenge"))
    return HTTPException(status_code=403)

@app.post("/webhook")
async def handle_incoming(request: Request):
    payload = await request.json()
    try:
        entry = payload["entry"][0]["changes"][0]["value"]
        if "messages" in entry:
            msg_obj = entry["messages"][0]
            phone = msg_obj["from"]
            body_text = msg_obj.get("text", {}).get("body", "Document uploaded")
            
            reply = think_and_reply(phone, body_text)
            
            requests.post(
                f"https://graph.facebook.com/v18.0/me/messages",
                headers={"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"},
                json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": reply}}
            )
    except Exception:
        pass
    return {"status": "ok"}