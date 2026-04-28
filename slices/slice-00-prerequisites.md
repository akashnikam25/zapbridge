# Slice 0: Prerequisites

**Estimated time:** ~1 hour  
**Goal:** Get one real GitHub webhook hitting your local machine before writing any app code.

---

## Install dependencies

```bash
brew install redis postgresql ngrok

pip install fastapi uvicorn "rq>=1.10" httpx cryptography anthropic \
  pydantic-settings psycopg2-binary structlog \
  pytest pytest-asyncio pytest-mock fakeredis
```

> `rq>=1.10` is required for the `Retry` class — older versions silently ignore it.

---

## External services to set up

1. **Slack** — Create a workspace, add an Incoming Webhook app, copy `SLACK_WEBHOOK_URL`.

2. **GitHub OAuth App** — Settings → Developer settings → OAuth Apps → New.  
   - Authorization callback URL: `http://localhost:8000/auth/callback`  
   - Copy `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

3. **GitHub Webhook** — On any repo you own: Settings → Webhooks → Add webhook.  
   - Payload URL: `{ngrok-url}/webhook` (fill in after step 4)  
   - Content type: `application/json`  
   - Secret: any string — save it as `GITHUB_WEBHOOK_SECRET`  
   - Events: "Send me everything" or just Pull requests + Pushes

4. **ngrok** — run in a separate terminal:
   ```bash
   ngrok http 8000
   ```
   Copy the `https://` URL and paste it into the GitHub webhook Payload URL above.

---

## Generate Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output — this is your `FERNET_KEY`.

---

## Create `.env`

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
DATABASE_URL=postgresql://localhost/zapbridge
REDIS_URL=redis://localhost:6379
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
FERNET_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_WEBHOOK_SECRET=...
```

---

## Start infrastructure

```bash
docker compose up -d   # or: brew services start redis postgresql
createdb zapbridge     # create the Postgres database
```

---

## Verify baseline

Open a PR (or push a commit) on the GitHub repo where you installed the webhook.  
You should see the POST appear in the ngrok terminal:

```
POST /webhook   200 OK
```

That's your baseline. Every slice adds to this reality.

---

## ngrok tip

ngrok generates a new URL on each restart, forcing you to re-register it in GitHub.  
To avoid this friction, use Smee.io instead:

```bash
npx smee-client --url https://smee.io/YOUR_CHANNEL \
  --target http://localhost:8000/webhook
```

The channel URL is stable across restarts.
