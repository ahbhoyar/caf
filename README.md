# CAF Agency WhatsApp Assistant

An AI-powered WhatsApp bot for the Italian CAF Agency that helps users with tax returns (Modello 730), income certification (ISEE & Bonus), immigration services, and operator support.

## Features

✅ **Multi-language Support** - English and Italian
✅ **AI-Powered Responses** - OpenAI GPT-4o-mini integration
✅ **Session Management** - SQLite database for user state
✅ **Google Sheets Integration** - Automatic syncing of requests
✅ **Production Ready** - Error handling, logging, validation
✅ **Webhook Signature Verification** - Secure WhatsApp integration
✅ **Health Checks** - Built-in monitoring endpoint

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose (optional)
- WhatsApp Business API access
- OpenAI API key
- Google Cloud service account

### Environment Setup

1. Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

2. Fill in your credentials:

```bash
OPENAI_API_KEY=sk-...
WHATSAPP_API_TOKEN=your_token
WHATSAPP_VERIFY_TOKEN=your_verify_token
GOOGLE_SPREADSHEET_ID=...
GOOGLE_CREDENTIALS_JSON={...}
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run application
python app.py
```

The app will start at `http://localhost:8000`

### Docker Deployment

```bash
# Build and run with Docker Compose
docker-compose up --build
```

### Render.com Deployment

1. Push to GitHub
2. Connect repository to Render.com
3. Create Web Service and select `render.yaml`
4. Add environment variables
5. Deploy

The service will automatically:
- Pull dependencies
- Initialize the database
- Start the application
- Create a persistent disk for data

## API Endpoints

### Webhook Verification

```
GET /webhook?hub.verify_token=<token>&hub.challenge=<challenge>
```

### Message Webhook

```
POST /webhook
Content-Type: application/json
```

### Health Check

```
GET /health
```

Returns:
```json
{
  "status": "healthy",
  "timestamp": "2026-06-02T12:00:00.000000",
  "version": "1.0.0"
}
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for GPT-4o-mini |
| `WHATSAPP_API_TOKEN` | Yes | WhatsApp Business API token |
| `WHATSAPP_VERIFY_TOKEN` | Yes | Webhook verification token |
| `GOOGLE_SPREADSHEET_ID` | Yes | Google Sheets ID for syncing |
| `GOOGLE_CREDENTIALS_JSON` | No | Google service account credentials |
| `DB_FILE` | No | SQLite database path (default: `/data/caf_state.db`) |
| `PORT` | No | Server port (default: `8000`) |
| `DEBUG` | No | Debug mode (default: `False`) |

## Architecture

```
┌─────────────────┐
│   WhatsApp      │
│   Incoming      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  FastAPI App    │
│  /webhook       │
└────────┬────────┘
         │
    ┌────┴────┐
    │          │
    ▼          ▼
┌────────┐  ┌──────────────┐
│Database│  │OpenAI Service│
│(SQLite)│  │(GPT-4o-mini) │
└────────┘  └──────┬───────┘
                   │
                   ▼
            ┌─────────────┐
            │ Tool Calls  │
            │  - Language │
            │  - Service  │
            │  - Sheet    │
            └──────┬──────┘
                   │
         ┌─────────┴──────────┐
         │                    │
         ▼                    ▼
    ┌─────────┐         ┌──────────┐
    │WhatsApp │         │Google    │
    │Response │         │Sheets    │
    └─────────┘         └──────────┘
```

## Logging

Application logs are written to stdout with timestamps:

```
2026-06-02 12:00:00 - __main__ - INFO - ✓ Configuration validated
2026-06-02 12:00:00 - __main__ - INFO - ✓ Database initialized
2026-06-02 12:00:01 - __main__ - INFO - Processing message from +39123456789: step=START
```

For production, redirect logs to a file:

```bash
python app.py > app.log 2>&1 &
```

## Error Handling

The application includes graceful error handling:

- **OpenAI API Timeout** → Returns default response
- **WhatsApp API Failure** → Logs error, sends fallback message
- **Database Error** → Logs error, sends error message
- **Invalid Webhook** → Returns 403 Forbidden
- **Missing Configuration** → Fails at startup with clear error

## Security

- ✅ WhatsApp webhook signature verification (HMAC-SHA256)
- ✅ Token validation on webhook endpoints
- ✅ No hardcoded secrets
- ✅ Secure credential handling for Google Sheets
- ✅ Request timeouts to prevent hanging
- ✅ CORS middleware configured

## Database Schema

```sql
CREATE TABLE sessions (
    phone TEXT PRIMARY KEY,
    language TEXT DEFAULT '',
    current_step TEXT DEFAULT 'START',
    selected_service TEXT DEFAULT '',
    collected_data TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Troubleshooting

### "Missing required environment variables"

Ensure all required env vars are set:

```bash
export OPENAI_API_KEY=sk-...
export WHATSAPP_API_TOKEN=...
export WHATSAPP_VERIFY_TOKEN=...
export GOOGLE_SPREADSHEET_ID=...
```

### "Invalid webhook signature"

Verify that `WHATSAPP_API_TOKEN` matches the token used by WhatsApp for signing.

### "Sheet sync failed"

Check that `GOOGLE_CREDENTIALS_JSON` is valid and the service account has access to the spreadsheet.

### "Database is locked"

Ensure only one instance is writing to the database. For multiple instances, use a networked database.

## Performance

- **Response Time**: ~2-3 seconds (includes OpenAI API call)
- **Database**: SQLite (suitable for <1000 concurrent users)
- **Memory**: ~150MB at startup
- **Scalability**: For production, migrate to PostgreSQL

## Future Improvements

- [ ] PostgreSQL support for scaling
- [ ] Redis caching for session management
- [ ] Conversation history with pagination
- [ ] File upload support
- [ ] SMS fallback
- [ ] Webhook retry logic
- [ ] Rate limiting
- [ ] Metrics/Prometheus integration

## License

MIT

## Support

For issues or questions, please open a GitHub issue.