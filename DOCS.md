# CrawlConda — Full Documentation

## What Is CrawlConda

CrawlConda is a fact-checking system. You give it a claim in plain English. It searches 24 live news RSS feeds, runs the text through a 4-node AI pipeline, and returns a source-grounded verdict — CONFIRMED, PARTIALLY CONFIRMED, UNCONFIRMED, or FALSE.

Every verdict is stored permanently on IPFS. Humans can confirm or challenge any verdict via Discord reactions, the web UI, or the REST API. The AI verdict and human votes are stored together, queryable forever. All verdicts sync in real time across Discord and all open browser tabs via Server-Sent Events (SSE).

It runs as three components:
- `crawlconda_swarm.py` — the Discord bot
- `api.py` — the REST API (FastAPI)
- `frontend/index.html` — the web UI (single-page app)

All three share the same ChromaDB database. A vote from Discord shows up on the web instantly, and vice versa.

---

## Requirements

- Python 3.10+
- A Discord bot token
- An xAI API key (for `grok-4-1-fast-reasoning`)
- A Pinata account (free tier works) for IPFS pinning

---

## Installation

```bash
git clone https://github.com/yourname/crawlconda
cd crawlconda
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
XAI_API_KEY=your_xai_key
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=your_channel_id
PINATA_JWT=your_pinata_jwt
```

### Getting each key

**XAI_API_KEY**
- Go to https://console.x.ai
- Create an API key
- Model used: `grok-4-1-fast-reasoning`

**DISCORD_TOKEN**
- Go to https://discord.com/developers/applications
- New Application → Bot → Reset Token → copy it
- Under Privileged Gateway Intents, enable: `Message Content Intent` and `Server Members Intent`
- Invite the bot to your server with these permissions: `Send Messages`, `Read Message History`, `Add Reactions`, `Embed Links`

**DISCORD_CHANNEL_ID**
- In Discord, right-click the channel → Copy Channel ID
- (Enable Developer Mode in Discord settings if you don't see this option)

**PINATA_JWT**
- Go to https://app.pinata.cloud
- API Keys → New Key → Admin → copy the JWT

---

## Running Locally

### Terminal 1 — API
```bash
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — Discord Bot
```bash
python3 crawlconda_swarm.py
```

### Terminal 3 — Frontend
```bash
cd frontend
python3 -m http.server 3000
```

Then open:
- Frontend → `http://localhost:3000`
- API docs → `http://localhost:8000/docs`
- API health → `http://localhost:8000/verdicts`

**In GitHub Codespaces:**
- Click the **Ports** tab at the bottom
- Set ports 3000 and 8000 to **Public** visibility
- Click the 🌐 globe icon next to each port to open in browser

All three processes share the same ChromaDB folder (`./crawlconda_data/`).

---

## How a Verification Works

Every `!verify` or `GET /verify` runs this pipeline:

```
User claim
    ↓
[1] Expander (LLM)
    Converts casual claim into 5-8 optimised RSS search keywords
    e.g. "is khamenei dead" → "Khamenei dead Ayatollah death Iran Supreme Leader"
    ↓
[2] Searcher (no LLM)
    Scans all 24 RSS feeds + Google News
    Scores each article by keyword match count
    Returns top 8 articles with full content
    ↓
[3] Scanner (LLM)
    Reads the 8 sources
    Extracts only facts explicitly stated — no outside knowledge added
    Returns max 4 bullet points
    ↓
[4] Verdict (LLM)
    Compares claim against extracted facts + full sources
    Issues one of 4 verdicts with exact headline citation
    ↓
[5] Publisher (LLM)
    Formats clean output for Discord embed or API response
    ↓
ChromaDB (local storage) + IPFS (permanent public record)
```

**Cost per request:** ~$0.0004 at current xAI pricing (4 LLM calls total)

**Time per request:** ~15–25 seconds (RSS fetching is the bottleneck)

**Cache behavior:** Identical or fuzzy-matched claims within 24 hours return instantly from cache with `"cached": true` — zero LLM cost, <100ms response time.

---

## Verdicts

| Verdict | When issued |
|---|---|
| ✅ CONFIRMED | Sources explicitly report the event described |
| 🟡 PARTIALLY CONFIRMED | Sources support part of the claim but key details differ |
| ⚠️ UNCONFIRMED | Sources found but none mention the claim |
| ❌ FALSE | Sources explicitly contradict the claim |

The LLM is instructed to go strictly by what sources say. It cannot issue CONFIRMED based on its own training knowledge — only on what the fetched articles state.

---

## Discord Usage

```
!verify [claim]
```

Examples:
```
!verify Iran launched missiles at Gulf energy facilities
!verify Apple released a new chip today
!verify WHO declared a new health emergency
!verify Did Messi score last night
!verify Is Khamenei dead
```

The bot sends a live status message that updates through 5 stages:
```
🔍  Expanding query...
📡  Scanning 24 sources...
🧠  Extracting facts...
⚖️  Issuing verdict...
[Status message deleted, rich embed posted]
```

The final embed includes:
- Verdict emoji + type as the title
- 2-sentence reasoning as the description
- Original claim field
- Top 3 sources as numbered links
- IPFS archive link
- Footer: "CrawlConda · Ground Truth Engine"

After the verdict posts, the bot adds 👍 and 👎 reactions. Click them to cast a human vote. One vote per user — changing your reaction updates your vote.

---

## Web UI

Open `http://localhost:3000` (or the Codespaces forwarded URL).

**Features:**
- **Verify page:** Submit claims, see results with sources and IPFS link
- **The Record page:** Browse all past verdicts with real-time updates
- **Filter bar:** Filter verdicts by type (All / Confirmed / Partial / Unconfirmed / False)
- **Vote buttons:** ▲/▼ with optimistic UI updates (instant feedback, reconciles in background)
- **Real-time sync:** New verdicts from Discord or other browser tabs appear instantly via SSE

**Branding:**
- Title: "Ground Truth Engine"
- Tagline: "Submit any claim. CrawlConda searches 24 live sources, runs a 4-node AI pipeline, and returns a source-grounded verdict — pinned permanently to IPFS."

---

## REST API

Base URL (local): `http://127.0.0.1:8000`

Interactive docs: `http://127.0.0.1:8000/docs`

### Endpoints

#### `GET /verify`
Runs a full verification and returns structured JSON.

```bash
curl "http://localhost:8000/verify?claim=Iran+struck+Qatar+gas+facilities"
```

Response:
```json
{
  "claim": "Iran struck Qatar gas facilities",
  "verdict": "CONFIRMED",
  "emoji": "✅",
  "summary": "VERDICT: CONFIRMED\n\nSources confirm...",
  "sources": [
    {"title": "Iran war live...", "url": "https://...", "source": "Al Jazeera"}
  ],
  "ipfs_hash": "QmWiRFiwUs3NX84ybLB9R7zjhv8nEL5S9ALK8t1RxKdGLE",
  "ipfs_url": "https://gateway.pinata.cloud/ipfs/Qm...",
  "timestamp": "2026-03-19T05:16:37+00:00",
  "claim_key": "iran struck qatar gas facilities",
  "cached": false
}
```

**Spam protection:**
- Rate limit: 5 requests per IP per hour → `429` if exceeded
- Claim cache: Fuzzy-matched claims within 24h return `"cached": true` instantly
- Minimum length: Claims < 8 chars return `400`

#### `POST /confirm/:ipfs_hash`
Cast a human vote on a verdict. One vote per user, re-voting updates it.

```bash
curl -X POST "http://localhost:8000/confirm/QmWiRFiwUs..." \
  -H "Content-Type: application/json" \
  -d '{"vote": "up", "user_id": "dipanshu"}'
```

Response:
```json
{"status": "recorded", "vote": "up"}
```

#### `GET /verdict/:ipfs_hash`
Fetch a single verdict with its current human vote counts.

```bash
curl "http://localhost:8000/verdict/QmWiRFiwUs..."
```

Response includes the full verdict data plus:
```json
{
  "human_upvotes": 3,
  "human_downvotes": 1,
  ...
}
```

#### `GET /verdicts`
List all past verdicts with vote counts.

```bash
curl "http://localhost:8000/verdicts?limit=50"
```

#### `GET /stream`
Server-Sent Events endpoint for real-time verdict push.

```javascript
const es = new EventSource('http://localhost:8000/stream');
es.addEventListener('new_verdict', e => {
  const data = JSON.parse(e.data);
  console.log('New verdict:', data.claim, data.verdict);
});
```

Emits `new_verdict` events whenever a verdict is created from Discord or web. The frontend uses this to update "The Record" page in real time across all open tabs.

#### `POST /recover`
Rebuild local ChromaDB index from all pins on Pinata.

```bash
curl -X POST "http://localhost:8000/recover"
```

Response:
```json
{"recovered": 12, "skipped": 0, "total_pins": 12}
```

Run this if `crawlconda_data/` is deleted or lost. Verdict data is always recoverable from IPFS; vote counts are not (they're only in ChromaDB).

---

## Data Storage

### ChromaDB (local)
Stored in `./crawlconda_data/`

Two collections:
- `verified_crawlconda` — every verdict, keyed by IPFS hash, with metadata: `claim_key` (normalized claim for cache lookups) and `timestamp`
- `human_votes` — every vote, keyed by `ipfs_hash:user_id`

This folder is created automatically on first run. Back it up if you want to preserve history.

### IPFS via Pinata
Every verdict is pinned to IPFS immediately after the swarm completes. The IPFS hash is the permanent ID for that verdict — used as the ChromaDB document ID, the API lookup key, and the Discord/web audit link.

View any verdict permanently at:
```
https://gateway.pinata.cloud/ipfs/[IPFS_HASH]
```

Browse all your pins at: https://app.pinata.cloud/pinmanager

---

## News Sources

24 feeds scanned on every request. All results scored by keyword relevance, top 8 passed to the LLM.

| Category | Sources |
|---|---|
| World | Google News RSS, BBC World, Al Jazeera, The Guardian, DW World, France24, Sky News, NYT, CNN, NPR |
| Business | BBC Business, CNBC, WSJ, Guardian Business |
| Technology | BBC Tech, TechCrunch, Ars Technica, Guardian Tech |
| Science | BBC Science, Science Daily, Guardian Science |
| US News | Guardian US |
| Sport | BBC Sport, ESPN |
| Fallback | DuckDuckGo Lite (only if all 24 feeds return zero matches) |

Date window: last 30 days. Google News RSS is query-specific and typically returns 60–100 entries per search.

---

## What It Can and Cannot Verify

**Works well:**
- Breaking world news — wars, elections, disasters, diplomacy
- Political claims about world leaders and governments
- Health emergencies, WHO/UN/international body announcements
- Business and market events — earnings, crashes, mergers
- Tech news — product launches, AI announcements, outages
- Science discoveries covered by major outlets
- Sports results and major sporting events

**Will not work well:**
- Anything older than 30 days
- Hyperlocal or regional news not covered by international outlets
- Opinion, satire, or prediction claims
- Latin America, Southeast Asia — limited dedicated coverage
- Very vague claims ("Is the economy bad?") — keywords too weak to match

---

## Cache Behavior

The cache uses **fuzzy matching** with a **24-hour window**.

**How it works:**
1. Claim is normalized: lowercase, strip punctuation, collapse whitespace
   - "Is Khamenei dead?" → `"is khamenei dead"`
   - "IS KHAMENEI DEAD!!" → `"is khamenei dead"` → cache hit ✅
2. ChromaDB metadata lookup by `claim_key` (O(1) index query, not O(n) scan)
3. If found and timestamp < 24h old → return cached verdict instantly with `"cached": true`
4. If not found or expired → run full pipeline, store with `claim_key` in metadata

**Benefits:**
- Zero LLM cost for duplicate queries
- <100ms response time vs 15–25s for full pipeline
- Handles punctuation/case variations automatically

**Limitations:**
- Only works for semantically identical claims — "Khamenei dead" and "Khamenei health update" won't match
- Old verdicts without `claim_key` in metadata: first request re-runs pipeline and backfills metadata, subsequent requests hit cache

---

## Testing Guide

### Manual Test Checklist

Run these tests in order after starting all three processes:

**1. API Health**
```bash
curl http://localhost:8000/verdicts
# Should return {"verdicts": [...], "count": N}
```

**2. Claim Too Short**
```bash
curl "http://localhost:8000/verify?claim=hi"
# Should return 400: "Claim too short. Please enter at least 8 characters."
```

**3. Rate Limit**
```bash
# Fire 6 requests rapidly from same IP
for i in {1..6}; do
  curl "http://localhost:8000/verify?claim=test+$i" &
done
wait
# 6th request should return 429: "Rate limit exceeded. Max 5 verifications per hour per IP."
```

**4. Cache Hit**
```bash
# First request
curl "http://localhost:8000/verify?claim=Is+Khamenei+dead"
# Returns "cached": false, takes 15-25s

# Second request with punctuation variation
curl "http://localhost:8000/verify?claim=is+khamenei+dead%3F%21"
# Returns "cached": true, takes <100ms
```

**5. Frontend — Verify Page**
- Open `http://localhost:3000`
- Type a claim → click "Investigate"
- Verify result appears with sources, IPFS link, and vote buttons
- Click ▲ or ▼ → count should update instantly

**6. Frontend — The Record Page**
- Click "The Record" in nav
- Verify filter chips load with counts
- Click a verdict card → should open on Verify page (not crash)
- Click different filter chips → list should update

**7. Real-Time Sync (SSE)**
- Open `http://localhost:3000` in two browser tabs
- Both on "The Record" page
- In tab 1: go to Verify page, submit a claim
- In tab 2: new verdict should appear at the top of the list instantly (no refresh needed)

**8. Discord Bot**
- In Discord: `!verify test claim`
- Bot should post 4 status updates, then delete and post a rich embed
- Embed should have colored left border, verdict emoji, sources, IPFS link
- React 👍 or 👎 → vote should be recorded (check `/verdict/:hash` endpoint)

**9. Discord → Web Sync**
- Open `http://localhost:3000` on "The Record" page
- In Discord: `!verify another test`
- Verdict should appear on web instantly after bot posts it

**10. Vote Sync**
- Submit a claim on web, vote ▲
- Check Discord embed for same claim → vote count should match
- (Note: Discord embeds don't auto-update — refresh by re-fetching via API)

---

## Troubleshooting

**Bot not responding to `!verify`**
- Check `Message Content Intent` is enabled in Discord Developer Portal
- Confirm the bot is in the correct server and has permission to send messages + embed links
- Check terminal for errors — if `DISCORD_TOKEN` is invalid, bot won't start

**`ModuleNotFoundError`**
```bash
pip install -r requirements.txt
```

**IPFS pinning fails**
- Check `PINATA_JWT` in `.env` is correct and not expired
- Pinata free tier has a 1GB storage limit — check your usage at https://app.pinata.cloud
- If quota exceeded, old pins will remain accessible but new pins will fail

**All feeds return 0 matches**
- The claim may be too vague — try being more specific
- The event may be older than 30 days
- DuckDuckGo fallback will attempt automatically

**`uvicorn api:app` fails on import**
- Make sure `crawlconda_swarm.py` is in the same directory
- Make sure `.env` is present and populated
- Check for syntax errors: `python3 -c "import api"`

**Frontend shows "Could not load verdict"**
- Check browser console for CORS errors
- Verify API is running on port 8000
- In Codespaces: confirm port 8000 is set to **Public** visibility

**SSE not connecting (no live dot on "The Record" page)**
- Check browser console for `/stream` connection errors
- Verify API is running and `/stream` endpoint returns `200 text/event-stream`
- In Codespaces: port 8000 must be **Public**, not Private

**Rate limit triggers immediately**
- The in-memory rate store persists until API restart
- Restart API to reset: `Ctrl+C` in Terminal 1, then `python3 -m uvicorn api:app --reload --port 8000`

**Cache not working**
- Old verdicts without `claim_key` in metadata won't hit cache on first request
- After first request, metadata is backfilled and subsequent requests hit cache
- Check response for `"cached": true` field

---

## Deploying to Railway

Railway runs both the API and Discord bot as two separate services from the same GitHub repo. The ChromaDB data folder is mounted as a persistent volume so it survives deploys.

### Step 1 — Push to GitHub

```bash
git add .
git commit -m "ready for deploy"
git push origin main
```

Make sure `.env` is in `.gitignore` — it is by default. Never push your keys.

### Step 2 — Create Railway project

1. Go to https://railway.app and sign in with GitHub
2. Click **New Project** → **Deploy from GitHub repo** → select your repo
3. Railway will detect the `Procfile` and start building

### Step 3 — Add environment variables

In Railway dashboard → your service → **Variables** tab, add all four:

```
XAI_API_KEY=
DISCORD_TOKEN=
DISCORD_CHANNEL_ID=
PINATA_JWT=
```

### Step 4 — Add the second service (Discord bot)

Railway runs one service by default (the API). To also run the bot:

1. In your Railway project → **New Service** → **GitHub repo** (same repo)
2. In that service's settings → **Start Command**: `python crawlconda_swarm.py`
3. Add the same 4 environment variables to this service too

### Step 5 — Add persistent volume for the API service

1. In the API service → **Volumes** tab → **Add Volume**
2. Mount path: `/app/crawlconda_data`

This keeps your ChromaDB data alive across deploys and restarts.

### Step 6 — Deploy frontend to Vercel

1. Go to https://vercel.com and sign in with GitHub
2. **New Project** → select your repo
3. Root directory: `frontend`
4. Deploy

Vercel will auto-detect `vercel.json` and serve `index.html` as an SPA.

### Step 7 — Update frontend API URL

In `frontend/index.html`, change:
```javascript
const API = "http://localhost:8000";
```
to:
```javascript
const API = "https://your-railway-api-url.up.railway.app";
```

Commit and push — Vercel will auto-redeploy.

### Step 8 — Test production

Railway gives the API service a public URL like:
```
https://crawlconda-api-production.up.railway.app
```

Test it:
```bash
curl "https://your-url.up.railway.app/verdicts"
```

Open your Vercel URL in browser and test the full flow.

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (Vercel)                        │
│                   frontend/index.html                       │
│                                                             │
│  • Ground Truth Engine UI                                  │
│  • Verify page + The Record page + About                   │
│  • Filter bar (All/Confirmed/Partial/Unconfirmed/False)    │
│  • Real-time SSE connection to API                          │
│  • Optimistic vote updates                                  │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP + SSE
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    API (Railway)                            │
│                      api.py                                 │
│                                                             │
│  GET  /verify       → run pipeline or return cache          │
│  POST /confirm      → record human vote                     │
│  GET  /verdict      → fetch single verdict + votes          │
│  GET  /verdicts     → list all verdicts                     │
│  GET  /stream       → SSE broadcast (real-time push)        │
│  POST /recover      → rebuild DB from Pinata                │
│                                                             │
│  • Rate limit: 5 req/IP/hour                                │
│  • Cache: 24h fuzzy match via claim_key metadata            │
│  • SSE broadcast to all connected clients                   │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ├─────────────────────────────────────┐
                      │                                     │
                      ▼                                     ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────┐
│   Discord Bot (Railway)         │   │   LangGraph Pipeline            │
│   crawlconda_swarm.py           │   │                                 │
│                                 │   │  [1] Expander (LLM)             │
│  !verify [claim]                │   │  [2] Searcher (24 RSS feeds)    │
│  → run_swarm()                  │   │  [3] Scanner (LLM)              │
│  → post rich embed              │   │  [4] Verdict (LLM)              │
│  → add 👍/👎 reactions          │   │  [5] Publisher (LLM)            │
│  → record votes on reaction     │   │                                 │
│                                 │   │  Cost: ~$0.0004/request         │
│  • 5-stage status updates       │   │  Time: 15-25s                   │
│  • Colored embed with sources   │   └─────────────────────────────────┘
│  • IPFS link in footer          │
└─────────────────────┬───────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              ChromaDB (Railway Volume)                      │
│              ./crawlconda_data/                             │
│                                                             │
│  verified_crawlconda collection:                            │
│    • Document ID: IPFS hash                                 │
│    • Metadata: claim_key (normalized), timestamp            │
│    • Body: full verdict JSON                                │
│                                                             │
│  human_votes collection:                                    │
│    • Document ID: ipfs_hash:user_id                         │
│    • Body: "up" or "down"                                   │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  IPFS (Pinata)                              │
│                                                             │
│  • Every verdict pinned immediately after pipeline          │
│  • Permanent backup — survives DB wipes                     │
│  • Publicly accessible via gateway.pinata.cloud             │
│  • POST /recover rebuilds ChromaDB from Pinata pins         │
└─────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
crawlconda/
├── crawlconda_swarm.py   # Discord bot + LangGraph pipeline
├── api.py                # FastAPI REST API + SSE
├── frontend/
│   ├── index.html        # Single-page web UI
│   └── vercel.json       # Vercel SPA config
├── requirements.txt      # Python dependencies
├── .env                  # API keys (never commit this)
├── .gitignore
├── Procfile              # Railway process definitions
├── railway.toml          # Railway build config
├── README.md
├── DOCS.md               # This file
└── crawlconda_data/      # ChromaDB local storage (auto-created)
```

---

## Known Limitations

1. **Cache only works for identical normalized claims** — "Khamenei dead" and "Khamenei health" won't match even though they're related
2. **Vote counts not stored on IPFS** — if ChromaDB is wiped, verdict data is recoverable via `/recover` but vote counts are lost
3. **30-day news window** — older events won't have sources
4. **Rate limit is in-memory** — resets on API restart, not persistent across deploys
5. **Discord embeds don't auto-update** — vote counts on Discord require manual refresh (web UI updates in real time)
6. **No semantic search** — keyword matching only, no vector embeddings
7. **Single LLM provider** — xAI only, no fallback to OpenAI/Anthropic
8. **No user authentication** — anyone can vote, user_id is self-reported

---

## Future Improvements

- Semantic cache using embeddings (match "Khamenei dead" with "Khamenei health")
- Persistent rate limiter using Redis
- Vote counts stored in IPFS metadata
- Multi-LLM fallback (xAI → OpenAI → Anthropic)
- User authentication via Discord OAuth
- Webhook notifications for new verdicts
- Export verdicts as CSV/JSON
- Admin dashboard for moderation

---

## Terminal Audit Trail

Every request logs a full trace with timestamps:

```
[05:35:42] [REQUEST] 'is khamenei dead' from dipanshu0207 in #crawlconda
[05:35:43] [SEARCHER] Expanding query with LLM
[05:35:47] [SEARCHER] Expanded query: Khamenei dead Ayatollah death Iran Supreme Leader
[05:35:48]   [Google News] 69 entries → 3 matched
[05:35:48]   [BBC] 27 entries → 0 matched
[05:35:48]   [Al Jazeera] 25 entries → 0 matched
             ...
[05:35:56] [SEARCHER] Done — 3 sources collected
[05:35:56] [SCANNER] Extracting key facts
[05:36:00] [SCANNER] → Ayatollah Ali Khamenei is dead at 86...
[05:36:00] [VERDICT] Analysing facts
[05:36:03] [VERDICT] → CONFIRMED
[05:36:03] [PUBLISHER] Formatting final signal
[05:36:08] [DONE] IPFS: QmdZVC2j6Ex5JhqwGHYLzjiQZLcSjgmog594FGA1syWtNW
[05:36:19] [VOTE] up on QmdZVC2j6Ex5Jhqw... by 1447517822962897006
```

---

## License

MIT

## Contributing

Pull requests welcome. For major changes, open an issue first.

## Support

- Discord: [discord.gg/4hX4f7cu](https://discord.gg/4hX4f7cu)
- Issues: GitHub Issues
- Docs: This file
