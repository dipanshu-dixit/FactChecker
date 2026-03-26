# CrawlConda — Ground Truth Engine

A multi-agent fact-checking system. Submit any claim — it searches 24 live RSS feeds, runs a 4-node AI pipeline, and returns a source-grounded verdict pinned permanently to IPFS. Humans can confirm or challenge every claim via Discord reactions, the web UI, or the REST API. All verdicts sync in real time across every open browser tab and Discord simultaneously via SSE.

<img width="1915" height="840" alt="Image" src="https://github.com/user-attachments/assets/c0096d7b-bc9a-45f0-853f-12558d982aae" />

## Quick Start

```bash
git clone https://github.com/dipanshu-dixit/FactChecker
cd crawlconda
pip install -r requirements.txt
```

Create `.env` in the project root:
```
XAI_API_KEY=your_xai_key
DISCORD_TOKEN=your_discord_bot_token
DISCORD_CHANNEL_ID=your_verify_channel_id
VERIFIED_CHANNEL_ID=your_verified_channel_id
PINATA_JWT=your_pinata_jwt
DISCORD_VERIFIED_WEBHOOK=https://discord.com/api/webhooks/...
INTERNAL_SECRET=any_random_string_here
WEB_URL=https://your-app.vercel.app
API_INTERNAL_URL=https://your-railway-service.up.railway.app
CHROMA_PATH=./crawlconda_data
```

**Terminal 1 — API:**
```bash
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Discord bot:**
```bash
python3 crawlconda_swarm.py
```

**Terminal 3 — Web frontend:**
```bash
cd frontend
python3 -m http.server 3000
```

Open `http://localhost:3000` in your browser.

> In GitHub Codespaces: use the forwarded URLs from the **Ports** tab instead of localhost. Set both ports to **Public** visibility.

---

## Verdicts

| Claims | Meaning |
|---|---|
| ✅ CONFIRMED | Sources explicitly report the event |
| 🟡 PARTIALLY CONFIRMED | Sources support part of the claim but not all details |
| ⚠️ UNCONFIRMED | Sources found but none mention the claim |
| ❌ FALSE | Sources explicitly contradict the claim |

---

## Discord

```
!verify [claim]
```

```
!verify Iran launched missiles at Gulf energy facilities
!verify Is Khamenei dead
!verify Apple released a new chip today
```

The bot posts a rich embed with verdict, reasoning, numbered sources, and an IPFS archive link. React 👍/👎 to cast a human vote.

---

## API

```
GET  /verify?claim=...           # run a verification (cached within 24h)
POST /confirm/:ipfs_hash         # cast a human vote {"vote": "up"/"down", "user_id": "..."}
GET  /verdict/:ipfs_hash         # fetch verdict + vote counts
GET  /verdicts?limit=50          # list all past verdicts
GET  /stream                     # SSE stream for real-time verdict push
POST /recover                    # rebuild ChromaDB from Pinata if DB is lost

# NEW: API Keys & Badges
POST /api-keys/generate          # generate free API key (100 requests/day)
GET  /api-keys/usage             # check your usage stats
GET  /badge/:ipfs_hash.svg       # get verification badge (SVG)
GET  /badge/:ipfs_hash/embed     # get HTML/Markdown embed codes
GET  /claim/:ipfs_hash           # shareable page with Open Graph tags
```

Interactive docs: `http://localhost:8000/docs`

**Full API Documentation:** [API_FEATURES.md](API_FEATURES.md)

**Public API Docs:** `https://fact-checker-teal.vercel.app/api-docs.html`

---

## Spam Protection

- **Rate limit:** 5 verifications per IP per hour. Returns `429` if exceeded.
- **Claim cache:** Identical or punctuation-variant claims within 24 hours return instantly from cache (`"cached": true`) — no LLM cost.
- **Minimum length:** Claims under 8 characters return `400`.

---

## Live Demo

Join the Discord server: [discord.gg/4hX4f7cu](https://discord.gg/ve3G7vfHNm)

## Full Documentation

See [DOCS.md](DOCS.md) for complete architecture, pipeline details, all 24 sources, API reference, known limitations, test guide, and deployment instructions.
