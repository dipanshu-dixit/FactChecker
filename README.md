# CrawlConda

A multi-agent fact-checking Discord bot. Searches RSS feeds + DuckDuckGo, runs a LangGraph swarm (Search → Scan → Verdict → Publish), stores results in ChromaDB, and pins to IPFS.

## Setup

1. Clone and install:
   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env` and fill in your keys:
   ```
   XAI_API_KEY=
   DISCORD_TOKEN=
   DISCORD_CHANNEL_ID=
   PINATA_JWT=
   ```

3. Run:
   ```bash
   python crawlconda_swarm.py
   ```

## Usage

In any Discord channel the bot has access to:
```
!verify Is it true that [claim]?
```

Example:
```
!verify Is it true that the WHO declared a new health emergency?
```

The bot will return a verdict (CONFIRMED / UNCONFIRMED / FALSE), reasoning, and sources with an IPFS link.

## What It Can Verify

✅ Works well:
- Breaking world news (wars, elections, disasters, diplomacy)
- Political claims about world leaders and governments
- Health emergencies, WHO/UN/international body announcements
- Events from the last 7 days covered by major outlets
- Claims with clear keywords that match news headlines

❌ Will not work well:
- Anything older than 30 days (outside the search window)
- Science, tech, sports, entertainment — feeds are world news only
- Hyperlocal or regional news not covered by international outlets
- Opinion, satire, or prediction claims — no factual source will confirm these
- Very short or vague claims with weak keywords (e.g. "Is the economy bad?")

## Sources

Searches all 7 sources on every request, ranks results by keyword relevance, returns top 8:

| Source | Type | Coverage |
|---|---|---|
| Google News RSS | Query-specific | Aggregates everything, 100+ entries |
| BBC World | RSS | Global, reliable |
| Al Jazeera | RSS | Global, strong Middle East/Asia |
| The Guardian World | RSS | Global, strong Europe/politics |
| DW World | RSS | Global, strong Europe/Africa |
| France24 | RSS | Global, strong Africa/Middle East |
| Sky News World | RSS | Global, breaking news focused |
| DuckDuckGo Lite | Scraper fallback | Only used if all 7 RSS feeds return nothing |

## How It Works

Each `!verify` runs a 4-node LangGraph swarm — 3 LLM calls total:

```
Searcher (no LLM) → Scanner (LLM call 1) → Verdict (LLM call 2) → Publisher (LLM call 3)
```

- Searcher: fetches and ranks news from all sources, no AI
- Scanner: extracts key facts from sources
- Verdict: returns CONFIRMED / UNCONFIRMED / FALSE with reasoning
- Publisher: formats the final Discord message with verdict, reasoning, and source links

Results are stored in ChromaDB locally and pinned to IPFS via Pinata.
