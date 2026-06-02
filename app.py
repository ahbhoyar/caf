"""
CAF Agency WhatsApp Assistant - Production Application
Handles WhatsApp interactions with OpenAI and Google Sheets integration
"""

import os
import logging
import sqlite3
import json
import hmac
import hashlib
from typing import Dict, Optional, Tuple
from datetime import datetime

import requests
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Application configuration from environment variables"""
    
    # API Keys
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    WA_TOKEN = os.getenv("WHATSAPP_API_TOKEN")
    VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
    SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
    GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "{}")
    
    # Paths
    DB_FILE = os.getenv("DB_FILE", "/data/caf_state.db")
    
    # API Endpoints
    OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
    WHATSAPP_API_URL = "https://graph.facebook.com/v18.0/me/messages"
    
    # Models & Timeouts
    OPENAI_MODEL = "gpt-4o-mini"
    REQUEST_TIMEOUT = 30
    
    # Environment
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    
    @classmethod
    def validate(cls):
        """Validate required environment variables at startup"""
        required = [
            ("OPENAI_API_KEY", cls.OPENAI_API_KEY),
            ("WHATSAPP_API_TOKEN", cls.WA_TOKEN),
            ("WHATSAPP_VERIFY_TOKEN", cls.VERIFY_TOKEN),
            ("GOOGLE_SPREADSHEET_ID", cls.SPREADSHEET_ID),
        ]
        
        missing = [name for name, value in required if not value]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        logger.info("✓ Configuration validated")


# ============================================================================
# DATA MODELS
# ============================================================================

class SessionData(BaseModel):
    """Session state data model"""
    language: str = ""
    current_step: str = "START"
    selected_service: str = ""
    collected_data: Dict = {}


class WhatsAppMessage(BaseModel):
    """WhatsApp incoming message model"""
    messaging_product: str
    entry: list


# ============================================================================
# DATABASE
# ============================================================================

class Database:
    """Database operations for session management"""
    
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.init()
    
    def init(self):
        """Initialize database and tables"""
        try:
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
            with sqlite3.connect(self.db_file) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        phone TEXT PRIMARY KEY,
                        language TEXT DEFAULT '',
                        current_step TEXT DEFAULT 'START',
                        selected_service TEXT DEFAULT '',
                        collected_data TEXT DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
                logger.info("✓ Database initialized")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def get_session(self, phone: str) -> SessionData:
        """Retrieve session data for a phone number"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT language, current_step, selected_service, collected_data FROM sessions WHERE phone = ?",
                    (phone,)
                )
                row = cursor.fetchone()
                
                if row:
                    return SessionData(
                        language=row[0] or "",
                        current_step=row[1] or "START",
                        selected_service=row[2] or "",
                        collected_data=json.loads(row[3] or "{}")
                    )
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for phone {phone}: {e}")
        except Exception as e:
            logger.error(f"Error retrieving session for {phone}: {e}")
        
        return SessionData()
    
    def save_session(self, phone: str, session: SessionData):
        """Save session data to database"""
        try:
            with sqlite3.connect(self.db_file) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sessions 
                    (phone, language, current_step, selected_service, collected_data, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    phone,
                    session.language,
                    session.current_step,
                    session.selected_service,
                    json.dumps(session.collected_data)
                ))
                conn.commit()
                logger.debug(f"Session saved for {phone}: step={session.current_step}")
        except Exception as e:
            logger.error(f"Error saving session for {phone}: {e}")
            raise


# ============================================================================
# EXTERNAL SERVICES
# ============================================================================

class GoogleSheetService:
    """Google Sheets integration"""
    
    def __init__(self, credentials_json: str, spreadsheet_id: str):
        self.credentials_json = credentials_json
        self.spreadsheet_id = spreadsheet_id
    
    def sync_request(self, phone: str, service: str, language: str, notes: str) -> bool:
        """Sync request data to Google Sheet"""
        if not self.spreadsheet_id:
            logger.warning("SPREADSHEET_ID not configured, skipping sheet sync")
            return False
        
        try:
            creds_dict = json.loads(self.credentials_json or "{}")
            if not creds_dict:
                logger.warning("Google credentials not configured")
                return False
            
            creds = Credentials.from_service_account_info(
                creds_dict,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            service_sheet = build('sheets', 'v4', credentials=creds)
            
            timestamp = datetime.now().isoformat()
            values = [[phone, service, language, notes, "Pending Operator Review", timestamp]]
            body = {'values': values}
            
            service_sheet.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="Sheet1!A:F",
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()
            
            logger.info(f"✓ Sheet sync successful for {phone}: {service}")
            return True
        
        except HttpError as e:
            logger.error(f"Google Sheets API error: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid Google credentials JSON: {e}")
        except Exception as e:
            logger.error(f"Sheet sync failed: {e}")
        
        return False


class OpenAIService:
    """OpenAI API integration"""
    
    # Tool definition for state management
    TOOLS = [{
        "type": "function",
        "function": {
            "name": "update_customer_state",
            "description": "Updates customer session state",
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
    
    SYSTEM_PROMPT = """You are an autonomous Italian CAF Agency Assistant helping with tax and administrative services.
Your role is to guide users through a structured conversation flow.

BEHAVIOR GUIDELINES:
1. **START Phase**: Greet warmly and ask user to select language:
   - 1. English
   - 2. Italiano

2. **MENU Phase**: Display available services:
   - 1. Modello 730 (Tax Return)
   - 2. ISEE & Bonus (Income Certification)
   - 3. Immigrazione (Immigration)
   - 4. Parla con un Operatore (Talk to Operator)

3. **COLLECTING Phase**: Request user's document name or details about their service request

4. **COMPLETE Phase**: Confirm receipt, summarize, and offer next steps

IMPORTANT:
- Be professional but friendly
- Use the selected language for all responses
- Validate user input before state transitions
- Always use the update_customer_state tool to track progress"""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
    
    def get_response(self, session: SessionData, user_message: str) -> Tuple[str, Optional[Dict]]:
        """
        Get AI response and potential state updates
        
        Returns: (bot_reply, tool_args) where tool_args may be None
        """
        try:
            system_prompt = self._build_system_prompt(session)
            
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                "tools": self.TOOLS,
                "tool_choice": "auto",
                "temperature": 0.7
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                Config.OPENAI_API_URL,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get('choices'):
                logger.error(f"Invalid OpenAI response: {data}")
                return self._default_response(session), None
            
            choice = data['choices'][0]['message']
            bot_reply = choice.get("content", "").strip()
            tool_args = None
            
            if choice.get("tool_calls"):
                try:
                    tool_args = json.loads(choice["tool_calls"][0]["function"]["arguments"])
                except (json.JSONDecodeError, IndexError, KeyError) as e:
                    logger.error(f"Error parsing tool arguments: {e}")
            
            return bot_reply or self._default_response(session), tool_args
        
        except requests.exceptions.Timeout:
            logger.error("OpenAI API timeout")
            return self._default_response(session), None
        except requests.exceptions.HTTPError as e:
            logger.error(f"OpenAI API error: {e.response.status_code} - {e.response.text}")
            return self._default_response(session), None
        except Exception as e:
            logger.error(f"Unexpected error in OpenAI service: {e}")
            return self._default_response(session), None
    
    @staticmethod
    def _build_system_prompt(session: SessionData) -> str:
        """Build personalized system prompt with current session state"""
        return f"""{OpenAIService.SYSTEM_PROMPT}

Current User State:
- Language: {session.language if session.language else 'Not set'}
- Step: {session.current_step}
- Service: {session.selected_service if session.selected_service else 'None'}
- Data Collected: {json.dumps(session.collected_data)}"""
    
    @staticmethod
    def _default_response(session: SessionData) -> str:
        """Provide default response based on language"""
        if session.language == "it":
            return "Grazie. Pratica registrata."
        return "Thank you. Service logged."


class WhatsAppService:
    """WhatsApp API integration"""
    
    def __init__(self, api_token: str, timeout: int = 30):
        self.api_token = api_token
        self.timeout = timeout
    
    def send_message(self, phone: str, message: str) -> bool:
        """Send message via WhatsApp API"""
        try:
            payload = {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {"body": message}
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                Config.WHATSAPP_API_URL,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            logger.info(f"✓ Message sent to {phone}")
            return True
        
        except requests.exceptions.HTTPError as e:
            logger.error(f"WhatsApp API error: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"Failed to send WhatsApp message to {phone}: {e}")
        
        return False


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title="CAF WhatsApp Assistant",
    description="AI-powered WhatsApp bot for CAF Agency",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
try:
    Config.validate()
    db = Database(Config.DB_FILE)
    openai_service = OpenAIService(Config.OPENAI_API_KEY, Config.OPENAI_MODEL, Config.REQUEST_TIMEOUT)
    whatsapp_service = WhatsAppService(Config.WA_TOKEN, Config.REQUEST_TIMEOUT)
    sheets_service = GoogleSheetService(Config.GOOGLE_CREDENTIALS_JSON, Config.SPREADSHEET_ID)
    logger.info("✓ All services initialized successfully")
except Exception as e:
    logger.critical(f"Failed to initialize services: {e}")
    raise


# ============================================================================
# WEBHOOK HANDLERS
# ============================================================================

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Verify WhatsApp webhook subscription"""
    try:
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        
        if token != Config.VERIFY_TOKEN:
            logger.warning(f"Invalid verify token attempt: {token}")
            raise HTTPException(status_code=403, detail="Invalid verify token")
        
        if not challenge:
            logger.error("Missing hub.challenge parameter")
            raise HTTPException(status_code=400, detail="Missing hub.challenge")
        
        logger.info("✓ Webhook verified")
        return Response(content=challenge, media_type="text/plain")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook verification error: {e}")
        raise HTTPException(status_code=500, detail="Verification failed")


@app.post("/webhook")
async def handle_webhook(request: Request):
    """Handle incoming WhatsApp messages"""
    try:
        payload = await request.json()
        
        # Validate webhook signature if X-Hub-Signature provided
        if "X-Hub-Signature-256" in request.headers:
            signature = request.headers["X-Hub-Signature-256"]
            if not _verify_signature(payload, signature, Config.WA_TOKEN):
                logger.warning("Invalid webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")
        
        # Process message
        if not payload.get("entry"):
            logger.warning("No entries in webhook payload")
            return {"status": "ok"}
        
        entry = payload["entry"][0].get("changes", [{}])[0].get("value", {})
        
        if "messages" not in entry:
            logger.debug("No messages in webhook entry")
            return {"status": "ok"}
        
        msg_obj = entry["messages"][0]
        phone = msg_obj.get("from")
        body_text = msg_obj.get("text", {}).get("body", "").strip()
        
        if not phone or not body_text:
            logger.warning(f"Invalid message data: phone={phone}, text_len={len(body_text)}")
            return {"status": "ok"}
        
        # Process message
        await _process_message(phone, body_text)
        return {"status": "ok"}
    
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook payload")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return {"status": "ok"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _verify_signature(payload: dict, signature: str, token: str) -> bool:
    """Verify WhatsApp webhook signature"""
    try:
        # Extract signature algorithm and hash
        if not signature.startswith("sha256="):
            return False
        
        provided_hash = signature.split("=")[1]
        payload_bytes = json.dumps(payload).encode()
        expected_hash = hmac.new(
            token.encode(),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(provided_hash, expected_hash)
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


async def _process_message(phone: str, user_message: str):
    """Process incoming message and send response"""
    try:
        # Get session
        session = db.get_session(phone)
        logger.info(f"Processing message from {phone}: step={session.current_step}")
        
        # Get AI response
        bot_reply, tool_args = openai_service.get_response(session, user_message)
        
        # Update session if tool was called
        if tool_args:
            if "language" in tool_args:
                session.language = tool_args["language"]
            if "selected_service" in tool_args:
                session.selected_service = tool_args["selected_service"]
            if "current_step" in tool_args:
                session.current_step = tool_args["current_step"]
            
            # Sync to Google Sheet if requested
            if tool_args.get("trigger_google_sync"):
                sheets_service.sync_request(
                    phone,
                    session.selected_service,
                    session.language,
                    tool_args.get("notes", "Data received")
                )
            
            # Save session
            db.save_session(phone, session)
        
        # Send reply
        if bot_reply:
            whatsapp_service.send_message(phone, bot_reply)
    
    except Exception as e:
        logger.error(f"Message processing failed for {phone}: {e}", exc_info=True)
        # Send fallback message
        fallback_msg = "Mi scusi, si è verificato un errore. Per favore, riprova più tardi." \
            if db.get_session(phone).language == "it" \
            else "Sorry, an error occurred. Please try again later."
        whatsapp_service.send_message(phone, fallback_msg)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
