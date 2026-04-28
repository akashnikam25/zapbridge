# ZapBridge — What We're Building & What We're Learning

> Built by Akash Nikam | Interview Prep Project for Zapier Senior Backend Engineer Role

---

## What Is ZapBridge?

ZapBridge is a **mini Zapier clone** — a real integration platform that connects GitHub to Slack using OAuth 2.0, webhooks, and AI summarization.

Think of it like this:

```
User logs in with GitHub (OAuth 2.0)
        ↓
GitHub sends an event to your server (Webhook)
        ↓
Your server validates + queues the event (HMAC + Redis)
        ↓
Worker picks it up and calls Claude AI (RQ Worker)
        ↓
Claude summarizes the event (AI Agent)
        ↓
Summary posted to Slack (REST API)
```

This is **exactly** how Zapier works internally — just at a smaller scale.

---

## Why Are We Building This?

Zapier's interview form asks 3 critical questions:

| Interview Question | ZapBridge Answer |
|---|---|
| Most complex REST API integration you built? | GitHub Issues API — pagination + rate limiting + backoff |
| OAuth 2.0 in production — how did you implement it? | GitHub OAuth — token storage, refresh, encryption, revocation |
| AI workflow you built? | Agent harness — Claude summarizes GitHub events, posts to Slack |

Without this project, you have **no story** for these questions.
With this project, you have **real code** running on your machine.

---

## What We're Learning — Concept by Concept

---

### 1. OAuth 2.0 Authorization Code Flow

**What it is:**
OAuth 2.0 is a protocol that lets your app access another app's data on behalf of a user — without ever seeing their password.

**Real-life analogy:**
Imagine a hotel key card. You don't get the master key (password). You get a temporary card (access token) that works only for your room (scope) and expires after checkout (token expiry).

**What we build:**
```
Step 1 — User clicks "Login with GitHub"
Step 2 — GitHub asks "Do you allow ZapBridge to access your repos?"
Step 3 — User says Yes → GitHub gives us an Authorization Code
Step 4 — We exchange the code for Access Token + Refresh Token
Step 5 — We encrypt both tokens and store in PostgreSQL
Step 6 — When Access Token expires → we silently use Refresh Token to get a new one
Step 7 — User never notices — they stay logged in
```

**What you learn:**
- Authorization code flow (not implicit, not client credentials)
- Access token vs refresh token — what each does
- Token expiry handling with 5-minute buffer
- Encrypted token storage — why plain text is a security risk
- Token revocation — what happens when user disconnects

**Why Zapier cares:**
Zapier stores OAuth tokens for 9,000+ apps. Every connection you make in Zapier is an OAuth token stored in their DB. This is their core infrastructure.

---

### 2. Encrypted Token Storage

**What it is:**
Storing sensitive tokens in the database safely — so even if the DB is breached, tokens can't be read.

**Real-life analogy:**
Like storing passwords in a safe with a combination lock — even the safe manufacturer can't read what's inside without the key.

**What we build:**
```python
# Encrypt before saving
encrypted = fernet.encrypt(token.encode())
db.save(encrypted)

# Decrypt when reading
token = fernet.decrypt(encrypted.encode())
```

**What you learn:**
- Fernet symmetric encryption (AES-128-CBC)
- Encryption key management via environment variables
- Why you never store raw OAuth tokens in plain text
- How to handle key rotation (advanced)

---

### 3. Webhook Receiver

**What it is:**
A webhook is when GitHub calls YOUR server — instead of you calling GitHub.

**Real-life analogy:**
Normal API = You call the restaurant to check if your food is ready (polling).
Webhook = Restaurant calls YOU when your food is ready (push).

**What we build:**
```
GitHub event happens (PR opened, issue created)
        ↓
GitHub sends POST request to your /webhook endpoint
        ↓
You validate the signature (is this really from GitHub?)
        ↓
You check Redis (have we processed this event before?)
        ↓
You push to RQ queue (process it async)
        ↓
Return 200 immediately (never make GitHub wait)
```

**What you learn:**
- Webhook vs polling — when to use each
- HMAC-SHA256 signature validation — how to verify the sender
- Idempotency with Redis SETNX — preventing duplicate processing
- Async processing — return 200 fast, process in background
- Dead letter queue — what happens when processing fails

**Why Zapier cares:**
Zapier receives millions of webhooks per day. This is their most critical infrastructure. They will almost certainly ask "design a webhook system" in the Systems Design round.

---

### 4. HMAC Signature Validation

**What it is:**
A way to verify that the webhook actually came from GitHub and not a fake attacker.

**Real-life analogy:**
Like a wax seal on an envelope — if the seal is broken or fake, you know the letter was tampered with.

**What we build:**
```python
import hmac, hashlib

def validate_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**What you learn:**
- HMAC (Hash-based Message Authentication Code)
- Why `hmac.compare_digest` instead of `==` (timing attack prevention)
- Shared secret between GitHub and your server
- Replay attack prevention using timestamps

---

### 5. Redis Idempotency

**What it is:**
Making sure the same webhook event is never processed twice — even if GitHub sends it multiple times.

**Real-life analogy:**
Like a bouncer at a club with a stamp — if you already have a stamp, you can't get in again. Each person (event) gets processed only once.

**What we build:**
```python
# Try to set key — only succeeds if key doesn't exist
result = redis.setnx(f"webhook:{delivery_id}", 1)
redis.expire(f"webhook:{delivery_id}", 86400)  # 24 hour TTL

if not result:
    return {"status": "already_processed"}  # Skip duplicate
```

**What you learn:**
- Redis SETNX (SET if Not eXists) — atomic idempotency check
- TTL (Time To Live) — auto-cleanup of old keys
- Why idempotency matters in distributed systems
- Delivery ID — GitHub's unique ID per webhook event

---

### 6. RQ Worker (Background Processing)

**What it is:**
A background worker that picks up jobs from Redis queue and processes them — separate from your web server.

**Real-life analogy:**
Like a kitchen in a restaurant — the waiter (FastAPI) takes your order and passes it to the kitchen (RQ Worker). The kitchen cooks it while the waiter serves other tables.

**What we build:**
```
FastAPI receives webhook → enqueues job in Redis
        ↓
RQ Worker picks up job
        ↓
Calls Claude API → gets summary
        ↓
Posts to Slack
        ↓
Marks job complete
```

**What you learn:**
- Producer-consumer pattern
- Why you never do heavy work in the request-response cycle
- Job retry logic — what happens on failure
- Dead letter queue — failed jobs after max retries

---

### 7. Rate Limiting + Exponential Backoff

**What it is:**
Handling GitHub's API limit (5000 requests/hour) gracefully — without crashing or spamming.

**Real-life analogy:**
Like a toll booth — if there's a queue, you wait and try again. You don't keep ramming the gate. And you wait longer each time to avoid making it worse.

**What we build:**
```python
def fetch_with_retry(url, headers, max_retries=5):
    for attempt in range(max_retries):
        resp = requests.get(url, headers=headers)

        if resp.status_code == 429:  # Rate limited
            wait = (2 ** attempt) + random.uniform(0, 1)  # Jitter
            time.sleep(wait)
            continue

        return resp.json()
```

**What you learn:**
- HTTP 429 Too Many Requests
- Exponential backoff — 1s, 2s, 4s, 8s, 16s
- Jitter — random delay to prevent thundering herd
- Retry-After header — GitHub tells you how long to wait
- Circuit breaker pattern (advanced)

---

### 8. Claude AI Agent Integration

**What it is:**
Using Claude API to intelligently summarize GitHub events before posting to Slack.

**Real-life analogy:**
Like having a smart assistant who reads all your GitHub notifications and sends you a 2-sentence WhatsApp message about what actually matters.

**What we build:**
```python
response = anthropic.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=150,
    messages=[{
        "role": "user",
        "content": f"""Summarize this GitHub event for a Slack notification.
        Be specific: what changed, who changed it, why it matters.
        Max 2 sentences. Event: {json.dumps(payload)}"""
    }]
)
```

**What you learn:**
- Anthropic Claude API basics
- Prompt engineering for structured output
- Token limits and cost management
- Temperature settings for consistent output
- How to integrate AI into a real pipeline (not just a chatbot)

---

### 9. Slack Notification via Incoming Webhook

**What it is:**
Posting a message to Slack programmatically using a webhook URL.

**What we build:**
```python
import httpx

async def post_to_slack(message: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            settings.SLACK_WEBHOOK_URL,
            json={"text": message}
        )
```

**What you learn:**
- Slack Incoming Webhooks (simplest Slack integration)
- Difference between Incoming Webhook vs Slack Bot Token vs OAuth
- Async HTTP calls with httpx

---

## Full Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                      ZapBridge                          │
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  GitHub  │───▶│   FastAPI    │───▶│  PostgreSQL   │  │
│  │  OAuth   │    │   Server     │    │  (tokens)     │  │
│  └──────────┘    └──────┬───────┘    └───────────────┘  │
│                         │                               │
│  ┌──────────┐           │            ┌───────────────┐  │
│  │  GitHub  │───▶  HMAC Validate    │     Redis     │  │
│  │ Webhook  │           │───────────▶│  (queue +     │  │
│  └──────────┘           │            │  idempotency) │  │
│                         │            └───────┬───────┘  │
│                         │                    │          │
│                         │            ┌───────▼───────┐  │
│                         │            │   RQ Worker   │  │
│                         │            └───────┬───────┘  │
│                         │                    │          │
│                         │            ┌───────▼───────┐  │
│                         │            │  Claude API   │  │
│                         │            └───────┬───────┘  │
│                         │                    │          │
│                         │            ┌───────▼───────┐  │
│                         │            │     Slack     │  │
│                         │            └───────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## Concepts Map — What Each Interview Round Tests

| Concept | Where You Built It | Interview Round |
|---|---|---|
| OAuth 2.0 flow | `app/auth/oauth.py` | Recruiter form Q3 |
| Encrypted token storage | `app/auth/tokens.py` | Recruiter form Q3 |
| Refresh token logic | `app/auth/tokens.py` | Job Fit Round |
| Webhook HMAC validation | `app/webhooks/validator.py` | Systems Design |
| Redis idempotency | `app/webhooks/receiver.py` | Systems Design |
| Async background processing | `app/workers/processor.py` | Job Fit Round |
| Rate limiting + backoff | `app/auth/oauth.py` | Job Fit Round |
| Claude AI integration | `app/workers/processor.py` | AI-Native Coding |
| Slack REST API | `app/workers/processor.py` | Recruiter form Q1 |
| Dead letter queue | `app/workers/processor.py` | Systems Design |

---

## Your Interview Story — How To Tell It

When the interviewer asks **"Tell me about a complex integration you built"** — say this:

> "I built ZapBridge — a mini integration platform similar to Zapier's core pipeline.
> It receives GitHub webhook events, validates HMAC signatures, uses Redis for idempotency,
> queues jobs with RQ, summarizes events with Claude AI, and posts to Slack.
> The most interesting challenge was the OAuth 2.0 token management —
> I encrypted refresh tokens with Fernet before storing in Postgres,
> built middleware that silently refreshes expired tokens,
> and handled revocation by catching 401s and forcing re-authentication.
> This taught me that OAuth is not just a login flow —
> it's a stateful trust contract between your app and the user's account."

That answer covers: REST APIs, OAuth, webhooks, Redis, async workers, AI agents, Slack — in 6 sentences.

---

## Day-by-Day Build Plan

| Day | What You Build | Gaps Closed |
|---|---|---|
| Day 1 | GitHub OAuth + encrypted token storage + GitHub Issues API | OAuth gap, REST API gap |
| Day 2 | Webhook receiver + HMAC validation + Redis idempotency + RQ worker + Claude + Slack | Webhook gap, AI gap |
| Day 3 | Polish + ARCHITECTURE.md + practice answers out loud | Storytelling |

---

## Key Terms Glossary

| Term | Simple Explanation |
|---|---|
| OAuth 2.0 | Protocol to access someone's data without their password |
| Access Token | Short-lived key (1 hour) to call APIs |
| Refresh Token | Long-lived key to get new access tokens |
| HMAC | Cryptographic signature to verify sender identity |
| Idempotency | Processing the same event only once, no matter how many times it arrives |
| Webhook | When another service calls YOUR server (push model) |
| Polling | When YOU call another service repeatedly to check for updates (pull model) |
| RQ (Redis Queue) | Background job queue using Redis |
| Dead Letter Queue | Where failed jobs go after max retries |
| Exponential Backoff | Waiting longer and longer between retries |
| Jitter | Random delay added to backoff to prevent thundering herd |
| Circuit Breaker | Stop calling a failing service temporarily to let it recover |
| Fernet | Python symmetric encryption library (AES-128-CBC) |
| SETNX | Redis command — SET only if key does Not eXist (atomic idempotency) |

---

*Built as interview preparation for Zapier Senior Backend Engineer — Enterprise Integrations Team*
*Stack: Python · FastAPI · PostgreSQL · Redis · RQ · Claude API · Slack*
