# CrawlConda Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         USER LAYER                          │
├─────────────────────────────────────────────────────────────┤
│  Web UI (Vercel)  │  Discord Bot  │  REST API  │  Settings  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      PROXY LAYER (Vercel)                   │
├─────────────────────────────────────────────────────────────┤
│  /api/proxy.js (GET)  │  /api/post-proxy.js (POST)         │
│  /api/stream.js (SSE) │  Timeout: 300s                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   API LAYER (Railway)                       │
├─────────────────────────────────────────────────────────────┤
│  FastAPI (api.py)                                           │
│  - /verify (with API key support)                           │
│  - /api-keys/* (generation, usage)                          │
│  - /badge/* (SVG, embed codes)                              │
│  - /claim/* (OG tags for social)                            │
│  - /stats (platform statistics)                             │
│  - /stream (SSE real-time updates)                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  VERIFICATION PIPELINE                      │
├─────────────────────────────────────────────────────────────┤
│  LangGraph Swarm (crawlconda_swarm.py)                     │
│  1. Searcher → Expand query, search 34 RSS feeds           │
│  2. Scanner → Extract facts from sources                    │
│  3. Verdict → Cross-reference, assess credibility           │
│  4. Publisher → Format final verdict                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     STORAGE LAYER                           │
├─────────────────────────────────────────────────────────────┤
│  ChromaDB (Railway Volume)                                  │
│  - verified_crawlconda (verdicts)                           │
│  - human_votes (vote records)                               │
│  - api_keys (hashed keys)                                   │
│                                                             │
│  Pinata IPFS (Permanent Archive)                            │
│  - Every verdict pinned immutably                           │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Frontend (Vercel)
- **index.html** - Main app (verify, results, voting)
- **settings.html** - API key management
- **api-docs.html** - Public API documentation
- **Proxy functions** - Route requests to Railway

### 2. Backend (Railway)
- **api.py** - FastAPI server (15 endpoints)
- **crawlconda_swarm.py** - Discord bot + verification pipeline
- **api_keys.py** - API key manager (SHA256 hashing)
- **badge_generator.py** - SVG badge generation

### 3. Data Sources (34 RSS Feeds)
- World News: BBC, Al Jazeera, Guardian, DW, France24, Sky, NYT, CNN, NPR, Reuters, Independent
- Business: BBC Business, CNBC, WSJ, Guardian Business, Financial Times
- Technology: BBC Tech, TechCrunch, Ars Technica, Guardian Tech, Wired, The Verge
- Science: BBC Science, Science Daily, Guardian Science, Nature
- US News: Guardian US, NYT US
- Sports: BBC Sport, ESPN
- Health: WHO, Guardian Health

## Data Flow

### Verification Request
```
User → Web UI → Vercel Proxy → Railway API → LangGraph Pipeline
                                                    ↓
                                            34 RSS Feeds
                                                    ↓
                                            xAI Grok-4 LLM
                                                    ↓
                                            ChromaDB + IPFS
                                                    ↓
                                            SSE Broadcast
                                                    ↓
                                    All connected clients
```

### Real-Time Sync
```
Discord !verify → Railway Bot → ChromaDB → SSE → Web UI
Web UI verify → Railway API → ChromaDB → SSE → Discord + Web
Vote (any platform) → ChromaDB → SSE → All platforms
```

## Key Features

### Rate Limiting
- **No API key**: 5 requests/hour per IP
- **Free API key**: 100 requests/day
- **Pro API key**: 1,000 requests/day

### Caching
- **Claim cache**: 24 hours (normalized text)
- **Search cache**: 5 minutes (300s TTL)
- **News window**: 90 days

### Security
- API keys hashed with SHA256
- CORS enabled for web apps
- Rate limiting per IP and per key
- Input validation on all endpoints

## Performance

### Timing
- Query expansion: ~4s
- Source search: ~18s (34 feeds)
- Fact extraction: ~8s
- Cross-referencing: ~7s
- Verdict generation: ~5s
- IPFS archival: ~15s
- **Total**: ~57 seconds average

### Scalability
- Current: 50-100 concurrent users
- Limit: 200+ concurrent users (1GB RAM)
- Cost: $10-20/month (Railway + xAI)

## File Structure

```
/workspaces/FactChecker/
├── api.py                    # FastAPI server (main)
├── crawlconda_swarm.py       # Discord bot + pipeline
├── api_keys.py               # API key management
├── badge_generator.py        # Badge SVG generation
├── requirements.txt          # Python dependencies
├── start.sh                  # Railway startup script
├── railway.toml              # Railway config
├── .env                      # Environment variables
├── frontend/
│   ├── index.html           # Main web app
│   ├── settings.html        # API key settings
│   ├── api-docs.html        # Public API docs
│   ├── api/
│   │   ├── proxy.js         # GET proxy (300s timeout)
│   │   ├── post-proxy.js    # POST proxy
│   │   └── stream.js        # SSE proxy
│   └── vercel.json          # Vercel config
├── README.md                # Quick start guide
├── DOCS.md                  # Full documentation
├── API_FEATURES.md          # API usage guide
├── DEPLOYMENT.md            # Deployment guide
└── test_api_features.py     # Test suite
```

## Environment Variables

```bash
# AI
XAI_API_KEY=your_xai_key

# Discord
DISCORD_TOKEN=your_bot_token
DISCORD_CHANNEL_ID=verify_channel_id
VERIFIED_CHANNEL_ID=verified_channel_id
DISCORD_VERIFIED_WEBHOOK=webhook_url

# IPFS
PINATA_JWT=your_pinata_jwt

# URLs
WEB_URL=https://fact-checker-teal.vercel.app
API_INTERNAL_URL=https://factchecker-production-3945.up.railway.app

# Security
INTERNAL_SECRET=random_string

# Storage
CHROMA_PATH=./crawlconda_data
```

## Deployment

- **Frontend**: Vercel (auto-deploy from main branch)
- **Backend**: Railway (auto-deploy from main branch)
- **Database**: ChromaDB on Railway volume (persistent)
- **IPFS**: Pinata (permanent archive)

## Monitoring

- Health check: `GET /health`
- Platform stats: `GET /stats`
- API key usage: `GET /api-keys/usage`
- Activity log: `GET /activity`

---

**Last Updated**: March 2026
**Version**: 2.0
**Status**: Production Ready 🚀
