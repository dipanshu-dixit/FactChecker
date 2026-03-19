# CrawlConda — Full Documentation

## What Is CrawlConda

CrawlConda is a fact-checking system. You give it a claim in plain English. It searches 24 live news RSS feeds, runs the text through a 4-node AI pipeline, and returns a source-grounded verdict — CONFIRMED, PARTIALLY CONFIRMED, UNCONFIRMED, or FALSE.

Every verdict is stored permanently on IPFS. Humans can confirm or challenge any verdict via Discord reactions or the REST API. The AI verdict and human votes are stored together, queryable forever.

It runs as two processes:
- `crawlconda_swarm.py` — the Discord bot
- `api.py` — the REST API (FastAPI)

Both share the same database. A vote from Discord shows up in the API and vice versa.

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
- Invite the bot to your server with these permissions: `Send Messages`, `Read Message History`, `Add Reactions`

**DISCORD_CHANNEL_ID**
- In Discord, right-click the channel → Copy Channel ID
- (Enable Developer Mode in Discord settings if you don't see this option)

**PINATA_JWT**
- Go to https://app.pinata.cloud
- API Keys → New Key → Admin → copy the JWT

---

## Running

### Discord Bot

```bash
python crawlconda_swarm.py
```

Terminal will show:
```
✅ CrawlConda bot live as CrawlConda#2837
```

### REST API

```bash
uvicorn api:app --reload --port 8000
```

Both can run at the same time in separate terminals. They share the same ChromaDB data folder.

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
    Extends date window: 48h → 7d → 30d until hits found
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
    Formats clean output for Discord or API response
    ↓
ChromaDB (local storage) + IPFS (permanent public record)
```

**Cost per request:** ~$0.0004 at current xAI pricing (4 LLM calls total)

**Time per request:** ~15–25 seconds (RSS fetching is the bottleneck)

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

The bot sends a live status message that updates through stages:
```
🔍 Searching 24 sources...
📌 Pinning to IPFS...
✅ [Final verdict card]
```

After the verdict posts, the bot adds 👍 and 👎 reactions. Click them to cast a human vote. One vote per user — changing your reaction updates your vote.

---

## REST API

Base URL (local): `http://127.0.0.1:8000`

Interactive docs: `http://127.0.0.1:8000/docs`

### Endpoints

#### `GET /verify`
Runs a full verification and returns structured JSON.

```
GET /verify?claim=Iran+struck+Qatar+gas+facilities
```

Response:
```json
{
  "claim": "Iran struck Qatar gas facilities",
  "verdict": "CONFIRMED",
  "emoji": "✅",
  "summary": "VERDICT: CONFIRMED\n\nSources confirm...",
  "sources": [
    {"title": "Iran war live...", "url": "https://...", "source": "Al Jazeera"},
    ...
  ],
  "ipfs_hash": "QmWiRFiwUs3NX84ybLB9R7zjhv8nEL5S9ALK8t1RxKdGLE",
  "ipfs_url": "https://gateway.pinata.cloud/ipfs/Qm...",
  "timestamp": "2026-03-19T05:16:37+00:00"
}
```

#### `POST /confirm/:ipfs_hash`
Cast a human vote on a verdict. One vote per user, re-voting updates it.

```
POST /confirm/QmWiRFiwUs3NX84ybLB9R7zjhv8nEL5S9ALK8t1RxKdGLE
Content-Type: application/json

{"vote": "up", "user_id": "dipanshu"}
```

Response:
```json
{"status": "recorded", "vote": "up"}
```

#### `GET /verdict/:ipfs_hash`
Fetch a single verdict with its current human vote counts.

```
GET /verdict/QmWiRFiwUs3NX84ybLB9R7zjhv8nEL5S9ALK8t1RxKdGLE
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

```
GET /verdicts?limit=20
```

---

## Data Storage

### ChromaDB (local)
Stored in `./crawlconda_data/`

Two collections:
- `verified_crawlconda` — every verdict, keyed by IPFS hash
- `human_votes` — every vote, keyed by `ipfs_hash:user_id`

This folder is created automatically on first run. Back it up if you want to preserve history.

### IPFS via Pinata
Every verdict is pinned to IPFS immediately after the swarm completes. The IPFS hash is the permanent ID for that verdict — used as the ChromaDB document ID, the API lookup key, and the Discord audit link.

View any verdict permanently at:
```
https://gateway.pinata.cloud/ipfs/[IPFS_HASH]
```

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

## File Structure

```
crawlconda/
├── crawlconda_swarm.py   # Discord bot + LangGraph swarm pipeline
├── api.py                # FastAPI REST API
├── requirements.txt      # Python dependencies
├── .env                  # API keys (never commit this)
├── .gitignore
├── README.md
├── DOCS.md               # This file
└── crawlconda_data/      # ChromaDB local storage (auto-created)
```

---

## Architecture Summary

```
                    ┌─────────────────────────────┐
                    │        crawlconda_swarm.py   │
                    │                             │
  Discord !verify ──►  expand_query()             │
                    │  search_news() × 24 feeds   │
                    │  scanner_node()             │
                    │  verdict_node()             │
                    │  publisher_node()           │
                    │         │                   │
                    │    run_swarm()              │
                    └─────────┬───────────────────┘
                              │
                    ┌─────────▼───────────────────┐
                    │  ChromaDB (crawlconda_data/) │
                    │  + IPFS via Pinata           │
                    └─────────┬───────────────────┘
                              │
                    ┌─────────▼───────────────────┐
                    │           api.py             │
                    │                             │
                    │  GET  /verify               │
                    │  POST /confirm/:hash        │
                    │  GET  /verdict/:hash        │
                    │  GET  /verdicts             │
                    └─────────────────────────────┘

  Discord 👍/👎 reactions ──► human_votes collection
  API POST /confirm      ──► human_votes collection (same)
```

---

## Troubleshooting

**Bot not responding to `!verify`**
- Check `Message Content Intent` is enabled in Discord Developer Portal
- Confirm the bot is in the correct server and has permission to send messages in the channel

**`ModuleNotFoundError`**
```bash
pip install -r requirements.txt
```

**IPFS pinning fails**
- Check `PINATA_JWT` in `.env` is correct and not expired
- Pinata free tier has a 1GB storage limit — check your usage at https://app.pinata.cloud

**All feeds return 0 matches**
- The claim may be too vague — try being more specific
- The event may be older than 30 days
- DuckDuckGo fallback will attempt automatically

**`uvicorn api:app` fails on import**
- Make sure `crawlconda_swarm.py` is in the same directory
- Make sure `.env` is present and populated

---

## Deploying Publicly (Railway)

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
3. Railway will detect the `railway.toml` and start building

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

### Step 6 — Get your public URL

Railway gives the API service a public URL like:
```
https://crawlconda-api-production.up.railway.app
```

Test it:
```bash
curl "https://your-url.up.railway.app/verdicts"
```

---

## Database: Where Everything Lives

```
crawlconda_data/          ← ChromaDB folder (local or Railway volume)
├── verified_crawlconda   ← every verdict, keyed by IPFS hash
└── human_votes           ← every vote, keyed by ipfs_hash:user_id
```

**IPFS via Pinata** is the permanent backup. Every verdict is pinned there the moment it's created. Even if `crawlconda_data/` is completely deleted, the verdict data still exists on IPFS forever.

View any verdict directly on Pinata:
```
https://gateway.pinata.cloud/ipfs/[IPFS_HASH]
```

Browse all your pins at: https://app.pinata.cloud/pinmanager

---

## Recovering the Database from Pinata

If `crawlconda_data/` is deleted or lost (e.g. Railway volume wiped, new machine), run:

```bash
curl -X POST "https://your-url.up.railway.app/recover"
```

Or locally:
```bash
curl -X POST "http://127.0.0.1:8000/recover"
```

This hits the Pinata API, fetches every pinned verdict, and rebuilds the local ChromaDB index. Already-existing records are skipped. Response:

```json
{"recovered": 12, "skipped": 0, "total_pins": 12}
```

After recovery, `/verdicts` and `/verdict/:hash` work again immediately. Human votes are stored separately in ChromaDB only — they are not on IPFS, so votes are lost if the DB is wiped. Verdict data is always recoverable; vote counts are not.
