# RideSwift - AI-Powered Vehicle Rental Agent
*Inspired by TDX Bengaluru 2025 Hackathon - built with 100% free tools*

## Demo
![RideSwift Demo Placeholder](https://via.placeholder.com/1200x600?text=RideSwift+Demo+GIF)

RideSwift demonstrates four connected flows:
1. Customer chat to AI-led booking in under two minutes.
2. Instant Slack manager approval/rejection with action buttons.
3. Vehicle return updates fleet status in real time.
4. Slack `/insurance` queries answered from RAG policy context.

## Architecture
RideSwift uses a 6-layer architecture:
1. **Layer 1:** React.js frontend (PWA + chat widget)
2. **Layer 2:** LangChain AI agents + Ollama (Mistral, local)
3. **Layer 3:** FastAPI backend (REST + WebSocket)
4. **Layer 4:** PostgreSQL + Redis + Kafka + Chroma DB + MinIO
5. **Layer 5:** Slack bot + Metabase + Celery tasks
6. **Layer 6:** Docker Compose + Nginx + GitHub Actions + Grafana

## Quick Start (5 commands)
```bash
git clone https://github.com/shivamgehlot/AI-Rental-Agent
cd AI-Rental-Agent
cp .env.example .env
docker-compose up -d
docker-compose exec backend python seed.py
```

## Pull the AI model (one-time)
```bash
docker-compose exec ollama ollama pull mistral
docker-compose exec ollama ollama pull nomic-embed-text
```

## Environment Variables
| Variable | Description | Example |
|---|---|---|
| DATABASE_URL | Async PostgreSQL URL for backend | `postgresql+asyncpg://admin:secret@postgres:5432/rideswift` |
| REDIS_URL | Redis connection string | `redis://redis:6379` |
| KAFKA_BROKER | Kafka bootstrap broker | `kafka:9092` |
| SECRET_KEY | JWT signing key | `change-this-to-a-random-32-char-string` |
| OLLAMA_URL | Ollama endpoint | `http://ollama:11434` |
| BACKEND_URL | Backend service URL | `http://backend:8000` |
| SLACK_BOT_TOKEN | Slack bot token | `xoxb-your-bot-token-here` |
| SLACK_APP_TOKEN | Slack app-level token (Socket Mode) | `xapp-your-app-token-here` |
| SLACK_SIGNING_SECRET | Slack request signing secret | `your-signing-secret-here` |
| SMTP_HOST | SMTP host for email notifications | `smtp.gmail.com` |
| SMTP_PORT | SMTP port | `587` |
| SMTP_USER | SMTP username | `your-gmail@gmail.com` |
| SMTP_PASS | SMTP app password | `your-app-password-here` |
| STRIPE_SECRET_KEY | Stripe secret for payment simulation | `sk_test_your-key-here` |

## The 4 Demo Flows
### Flow 1 - Customer chats and books a vehicle
```bash
curl -X POST http://localhost:8001/agent/chat \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"I need an SUV from Airport for 3 days starting tomorrow\",\"customer_id\":\"demo-customer\"}"
```

### Flow 2 - Slack manager confirms/rejects booking
1. Create a booking from frontend or API.
2. Slack bot posts to `#pickup-managers` with **Confirm** and **Reject** buttons.
3. Manager action updates booking state through backend.

### Flow 3 - Vehicle return updates live status
```bash
curl -X PATCH http://localhost:8000/api/bookings/<booking_id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"status\":\"completed\"}"
```
Inventory updates are broadcast to Redis/WebSocket consumers in real time.

### Flow 4 - Slack `/insurance` RAG response
```bash
curl -X POST http://localhost:8002/rag/query/demo-customer \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"Is flood damage covered?\"}"
```
Expected seeded answer includes: **Flood damage: NOT covered**.

## Slack Setup
1. Create a Slack app at `https://api.slack.com/apps`.
2. Enable **Socket Mode** and generate an app token.
3. Add bot scopes: `commands`, `chat:write`, `channels:read`, `channels:history`.
4. Install app to your workspace and copy bot token/signing secret.
5. Configure slash commands:
   - `/insurance`
   - `/return`
   - `/status`
   - `/fleet`
6. Set tokens/secrets in `.env`, then restart `slack-bot` service.

## Tech Stack
| Layer | Tools |
|---|---|
| Frontend | React, Vite, Tailwind, Zustand |
| AI Agent | LangChain, Ollama (Mistral) |
| Backend API | FastAPI, SQLAlchemy, WebSocket |
| Data & Messaging | PostgreSQL, Redis, Kafka |
| RAG | Chroma DB, MinIO |
| Ops & Observability | Docker Compose, Nginx, Prometheus, Grafana |
| Collaboration | Slack Bolt |
