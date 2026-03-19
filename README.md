# CrawlConda

A multi-agent fact-checking system. Give it a claim — it searches 24 live RSS feeds, runs a 4-node AI pipeline, and returns a source-grounded verdict pinned permanently to IPFS. Humans can confirm or challenge every verdict via Discord reactions or REST API.

## Quick Start

```bash
git clone https://github.com/yourname/crawlconda
cd crawlconda
pip install -r requirements.txt
```

Fill in `.env`:
```
XAI_API_KEY=
DISCORD_TOKEN=
DISCORD_CHANNEL_ID=
PINATA_JWT=
```

Run the Discord bot:
```bash
python crawlconda_swarm.py
```

Run the REST API:
```bash
uvicorn api:app --reload --port 8000
```

## Usage

```
!verify [claim]
```

```
!verify Iran launched missiles at Gulf energy facilities
!verify Is Khamenei dead
!verify Apple released a new chip today
```

## Verdicts

| Verdict | Meaning |
|---|---|
| ✅ CONFIRMED | Sources explicitly report the event |
| 🟡 PARTIALLY CONFIRMED | Sources support part of the claim but not all details |
| ⚠️ UNCONFIRMED | Sources found but none mention the claim |
| ❌ FALSE | Sources explicitly contradict the claim |

## API

```
GET  /verify?claim=...        # run a verification
POST /confirm/:ipfs_hash      # cast a human vote {"vote": "up"/"down", "user_id": "..."}
GET  /verdict/:ipfs_hash      # fetch verdict + vote counts
GET  /verdicts                # list all past verdicts
```

Interactive docs: `http://localhost:8000/docs`

## Full Documentation

See [DOCS.md](DOCS.md) for complete setup guide, architecture, all 24 sources, API reference, and troubleshooting.
