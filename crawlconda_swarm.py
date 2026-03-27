from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from typing import TypedDict
import discord
from discord.ext import commands
import asyncio
import chromadb
import feedparser
import json
import httpx
import time
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from urllib.parse import quote_plus  # CLEANED: moved from inside search_news()
import requests  # CLEANED: moved from inside ddg_fallback()
from bs4 import BeautifulSoup  # CLEANED: moved from inside ddg_fallback()
load_dotenv()

# ── Constants ──────────────────────────────────────────────────────────────────
# CLEANED: All magic numbers and hardcoded strings extracted as named constants
MODEL_NAME         = "grok-4-1-fast-reasoning"
MODEL_BASE_URL     = "https://api.x.ai/v1"
MODEL_MAX_TOKENS   = 600
IPFS_GATEWAY       = "https://gateway.pinata.cloud/ipfs/"
PINATA_PIN_URL     = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
TIMEOUT_PINATA     = 30
TIMEOUT_DDG        = 8
SEARCH_CACHE_TTL   = 300
SEARCH_CACHE_MAX   = 100
CHROMA_PATH        = os.getenv("CHROMA_PATH", "/app/crawlconda_data")  # CLEANED: Railway volume path
COL_VERDICTS       = "verified_crawlconda"
COL_VOTES          = "human_votes"
WEB_URL            = os.getenv("WEB_URL", "https://fact-checker-teal.vercel.app").strip()

# CLEANED: API_INTERNAL_URL for cross-process HTTP broadcast
API_INTERNAL_URL = (
    os.getenv("API_INTERNAL_URL", "")
    or f"http://localhost:{os.getenv('PORT', '8080')}"
)
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")

def _broadcast(data: dict):
    """POST to API process via HTTP — the only way to 
    reach SSE clients in a separate OS process."""
    def _post():
        try:
            import urllib.request as _req
            import json as _json
            body = _json.dumps(data).encode()
            req  = _req.Request(
                f"{API_INTERNAL_URL}/internal/broadcast",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Secret": INTERNAL_SECRET,
                },
                method="POST"
            )
            with _req.urlopen(req, timeout=3) as resp:
                pass
        except Exception as e:
            print(f"[BROADCAST] Failed: {e}")
    
    import threading
    threading.Thread(target=_post, daemon=True).start()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
def _safe_int(val, default=0):
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default

DISCORD_CHANNEL_ID  = _safe_int(os.getenv("DISCORD_CHANNEL_ID"), 0)
VERIFIED_CHANNEL_ID = _safe_int(os.getenv("VERIFIED_CHANNEL_ID"), 0)
PINATA_JWT = os.getenv("PINATA_JWT")

_llm = None

def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=MODEL_NAME,  # CLEANED: use constant
            temperature=0,
            api_key=os.getenv("XAI_API_KEY"),
            base_url=MODEL_BASE_URL,  # CLEANED: use constant
            max_tokens=MODEL_MAX_TOKENS,  # CLEANED: use constant
            max_retries=1,
        )
    return _llm

RSS_FEEDS = [
    # World / Breaking News
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.theguardian.com/world/rss",
    "https://rss.dw.com/rdf/rss-en-world",
    "https://www.france24.com/en/rss",
    "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "http://rss.cnn.com/rss/edition_world.rss",
    "https://feeds.npr.org/1004/rss.xml",
    "https://www.reuters.com/rssFeed/worldNews",
    "https://www.independent.co.uk/news/world/rss",
    # Business / Economy
    "http://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "https://www.theguardian.com/business/rss",
    "https://www.ft.com/?format=rss",
    # Technology
    "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theguardian.com/technology/rss",
    "https://www.wired.com/feed/rss",
    "https://www.theverge.com/rss/index.xml",
    # Science
    "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://www.sciencedaily.com/rss/top/science.xml",
    "https://www.theguardian.com/science/rss",
    "https://www.nature.com/nature.rss",
    # US News
    "https://www.theguardian.com/us-news/rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
    # Sport
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://www.espn.com/espn/rss/news",
    # Health
    "https://www.who.int/rss-feeds/news-english.xml",
    "https://www.theguardian.com/society/health/rss",
]

class State(TypedDict):
    content: str
    sources: str
    scanned: str
    verdict: str
    published: str

SOURCE_NAMES = {
    "news.google.com": "Google News",
    "feeds.bbci.co.uk": "BBC",
    "www.aljazeera.com": "Al Jazeera",
    "www.theguardian.com": "The Guardian",
    "rss.dw.com": "DW World",
    "www.france24.com": "France24",
    "feeds.skynews.com": "Sky News",
    "rss.nytimes.com": "NYT",
    "rss.cnn.com": "CNN",
    "feeds.npr.org": "NPR",
    "www.cnbc.com": "CNBC",
    "feeds.a.dj.com": "WSJ",
    "techcrunch.com": "TechCrunch",
    "feeds.arstechnica.com": "Ars Technica",
    "www.sciencedaily.com": "Science Daily",
    "www.espn.com": "ESPN",
    "www.reuters.com": "Reuters",
    "www.independent.co.uk": "The Independent",
    "www.ft.com": "Financial Times",
    "www.wired.com": "Wired",
    "www.theverge.com": "The Verge",
    "www.nature.com": "Nature",
    "www.who.int": "WHO",
}

def log(msg: str):
    print(f"[{datetime.now(tz=timezone.utc).strftime('%H:%M:%S')}] {msg}")

def search_news(query: str) -> str:
    keywords = [w.lower() for w in query.split() if len(w) > 3]
    # BUG 2 FIX: fallback for short queries
    if not keywords:
        keywords = [w.lower() for w in query.split() if w]
    # CLEANED: quote_plus now imported at top
    google_rss = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    feeds = [google_rss] + RSS_FEEDS
    hits = []
    for url in feeds:
        domain = url.split("/")[2]
        name = SOURCE_NAMES.get(domain, domain)
        try:
            feed = feedparser.parse(url)
            matched = 0
            for entry in feed.entries[:15]:
                try:
                    # Accept entries from last 90 days instead of 30
                    if (entry.get("published_parsed") and
                            time.time() - time.mktime(
                                entry.published_parsed) > 86400 * 90):
                        continue
                except (TypeError, ValueError, OverflowError):
                    pass  # malformed date — include the entry
                text = (entry.get("title", "") + " " + entry.get("summary", "") + " " + entry.get("description", "")).lower()
                match_count = sum(1 for k in keywords if k in text)
                if match_count >= max(1, len(keywords) // 2):
                    desc = (
                        entry.get("content", [{}])[0].get("value", "") or
                        entry.get("summary", "") or
                        entry.get("description", "")
                    )[:800]
                    # BUG 1 FIX: safe access to title and link
                    title = entry.get("title", "").strip()
                    link  = entry.get("link",  "").strip()
                    if not title or not link:
                        continue
                    hits.append((match_count, title, link, name, desc))
                    matched += 1
            log(f"  [{name}] {len(feed.entries)} entries → {matched} matched")
        except Exception as e:
            log(f"  [{name}] ERROR — {e}")
    if not hits:
        return "No recent matching reports found."
    hits.sort(key=lambda x: x[0], reverse=True)
    return "|||".join(f"{title}||{link}||{src}||{desc}" for _, title, link, src, desc in hits[:8])

def ddg_fallback(query: str) -> str:
    try:
        # CLEANED: requests and BeautifulSoup now imported at top
        q = requests.utils.quote(query)
        resp = requests.get(
            f"https://lite.duckduckgo.com/lite/?q={q}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=TIMEOUT_DDG  # CLEANED: use constant
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = [a for a in soup.find_all("a", href=True) if a.get("href", "").startswith("http")][:5]
        log(f"  [DuckDuckGo] fallback → {len(results)} results")
        return "|||".join(f"{a.get_text(strip=True)}||{a['href']}||DuckDuckGo||" for a in results)
    except Exception as e:
        log(f"  [DuckDuckGo] ERROR — {e}")
        return ""

def sources_for_llm(raw: str) -> str:
    out = []
    for entry in raw.split("|||"):
        parts = entry.split("||")
        if len(parts) >= 4:
            out.append(f"[{parts[2]}] HEADLINE: {parts[0]}\nDESCRIPTION: {parts[3]}")
        elif len(parts) >= 3:
            out.append(f"[{parts[2]}] HEADLINE: {parts[0]}")
    return "\n\n".join(out)

def expand_query(text: str) -> str:
    prompt = (
        f"Convert this claim into 5-8 specific search keywords for a news RSS search. "
        f"Return ONLY the keywords as a single line, space-separated, no explanation.\n"
        f"Claim: {text}"
    )
    raw = get_llm().invoke(prompt).content.strip()[:200]
    # BUG 1 FIX: Remove quotes that break keyword splitting
    clean = raw.replace('"', '').replace("'", '').strip()
    return clean

_search_cache: dict = {}  # CLEANED: TTL and MAX now module-level constants

def cached_search(query: str) -> str:
    now = time.time()
    if query in _search_cache:
        result, ts = _search_cache[query]
        if now - ts < SEARCH_CACHE_TTL:  # CLEANED: use constant
            log(f"[SEARCH_CACHE] Hit for: {query[:50]}")
            return result
    result = search_news(query)
    if len(_search_cache) >= SEARCH_CACHE_MAX:  # CLEANED: use constant
        oldest = min(_search_cache, key=lambda k: _search_cache[k][1])
        del _search_cache[oldest]
    _search_cache[query] = (result, now)
    return result

def searcher_node(state: State):
    log("[SEARCHER] Expanding query with LLM")
    expanded = expand_query(state["content"])
    log(f"[SEARCHER] Expanded query: {expanded}")
    sources = cached_search(expanded)
    if "No recent matching" in sources:
        log("[SEARCHER] RSS empty — trying DuckDuckGo fallback")
        ddg = ddg_fallback(expanded)
        if ddg:
            sources = ddg
    
    # Count real sources
    real = [s for s in sources.split("|||") 
            if len(s.split("||")) >= 3 
            and s.split("||")[1].strip().startswith("http")]
    
    # Retry with simplified 2-3 keyword query if weak results
    if len(real) < 2:
        log("[SEARCHER] Weak results — retrying with simplified query")
        # Extract just the key nouns from expanded query
        simple_prompt = (
            f"Extract only the 2-3 most important nouns or names "
            f"from this query as a search string. Return ONLY the "
            f"words, nothing else.\nQuery: {expanded}"
        )
        simple_query = get_llm().invoke(simple_prompt).content.strip()[:100]
        log(f"[SEARCHER] Simplified query: {simple_query}")
        retry_sources = search_news(simple_query)
        retry_real = [s for s in retry_sources.split("|||")
                      if len(s.split("||")) >= 3
                      and s.split("||")[1].strip().startswith("http")]
        if len(retry_real) > len(real):
            sources = retry_sources
            log(f"[SEARCHER] Retry found {len(retry_real)} sources")
    
    count = len(sources.split("|||")) if "|||" in sources else 0
    log(f"[SEARCHER] Done — {count} sources collected")
    return {"sources": sources}

def scanner_node(state: State):
    log("[SCANNER] Extracting key facts")
    sources = state.get("sources", "")
    real_sources = [
        s for s in sources.split("|||")
        if len(s.split("||")) >= 3
        and s.split("||")[0].strip()
    ]
    if not real_sources:
        log("[SCANNER] No sources to scan")
        return {"scanned": "No sources were found for this claim."}
    plain = sources_for_llm(state["sources"])
    prompt = (
        f"Claim: {state['content'][:300]}\n\n"
        f"News sources retrieved:\n{plain[:2500]}\n\n"
        f"FACT EXTRACTION RULES:\n"
        f"1. Extract ONLY facts explicitly stated in the sources above.\n"
        f"2. Do NOT add any outside knowledge or assumptions.\n"
        f"3. Read EVERY headline literally as a reported fact.\n"
        f"4. If multiple sources report the same fact, note this.\n"
        f"5. If sources contradict each other, note both versions.\n"
        f"6. Include the source name for each fact extracted.\n\n"
        f"CRITICAL: Headlines are facts, not opinions. If a headline says "
        f"'X cuts output by 17%' — that means X happened and is a confirmed "
        f"fact from that source. If a headline says 'Attack on Y' — Y was "
        f"attacked, state it with the source name.\n\n"
        f"Format: Extract up to 6 bullet points, each with [SOURCE NAME] prefix.\n"
        f"Example: [BBC] Iran launched missiles at Israeli bases.\n"
        f"Example: [Reuters] Attack caused 17% reduction in LNG output.\n"
    )
    scanned = get_llm().invoke(prompt).content[:800]
    log(f"[SCANNER] → {scanned[:120]}")
    return {"scanned": scanned}

def verdict_node(state: State):
    log("[VERDICT] Analysing facts")
    sources = state.get("sources", "")
    real_sources = [
        s for s in sources.split("|||")
        if len(s.split("||")) >= 3
        and s.split("||")[0].strip()
        and s.split("||")[1].strip().startswith("http")
    ]
    if not real_sources:
        log("[VERDICT] No real sources found — returning UNCONFIRMED")
        return {
            "verdict": (
                "VERDICT: UNCONFIRMED\n\n"
                "REASONING: No sources were located across 34 monitored feeds "
                "for this claim. Cannot confirm or deny without source material.\n"
                "KEY SOURCE: None"
            )
        }
    plain = sources_for_llm(state["sources"])
    prompt = (
        f"You are a strict evidence-based fact-checker. "
        f"Your job is to determine if the SPECIFIC claim is "
        f"directly answered by the sources provided.\n\n"
        f"Claim: {state['content'][:300]}\n\n"
        f"Facts extracted from sources:\n{state['scanned'][:800]}\n\n"
        f"Full sources:\n{plain[:2500]}\n\n"
        f"STRICT FACT-CHECKING RULES:\n"
        f"1. CROSS-REFERENCE: Check if multiple independent sources "
        f"report the same fact. Single-source claims are weaker.\n"
        f"2. SOURCE CREDIBILITY: Prioritize established news outlets "
        f"(BBC, Reuters, NYT, Guardian) over tabloids or blogs.\n"
        f"3. CONTRADICTION CHECK: If sources contradict each other, "
        f"note this explicitly and downgrade confidence.\n"
        f"4. TEMPORAL ACCURACY: Check if the claim's timeframe "
        f"matches source dates. 'Today' claims need recent sources.\n"
        f"5. SPECIFICITY: Vague claims ('might', 'could', 'possibly') "
        f"are UNCONFIRMED unless sources provide concrete evidence.\n\n"
        f"VERDICT CRITERIA:\n"
        f"- CONFIRMED: Multiple credible sources explicitly report "
        f"the event with consistent details. Direct evidence exists.\n"
        f"- PARTIALLY CONFIRMED: Some sources support parts of the claim "
        f"but key details are missing, contradicted, or uncertain.\n"
        f"- UNCONFIRMED: Sources exist on the topic but provide no "
        f"direct evidence the specific event occurred. OR only one "
        f"source reports it without corroboration.\n"
        f"- FALSE: Multiple credible sources explicitly contradict "
        f"the claim with evidence.\n\n"
        f"CRITICAL ANALYSIS REQUIRED:\n"
        f"- Count how many independent sources confirm the claim\n"
        f"- Note any contradictions between sources\n"
        f"- Assess source credibility (established outlets vs unknown)\n"
        f"- Check if evidence is direct or circumstantial\n"
        f"- Verify timeframes match the claim\n\n"
        f"Respond in exactly this format:\n"
        f"VERDICT: [CONFIRMED / PARTIALLY CONFIRMED / UNCONFIRMED / FALSE]\n"
        f"REASONING: [2-3 sentences. MUST include: (1) number of sources "
        f"confirming, (2) any contradictions found, (3) source credibility "
        f"assessment, (4) what specific evidence exists or is missing.]\n"
        f"KEY SOURCE: [exact headline, or 'None' if no direct source]"
    )
    verdict = get_llm().invoke(prompt).content[:800]
    log(f"[VERDICT] → {verdict[:120]}")
    return {"verdict": verdict}

def publisher_node(state: State):
    log("[PUBLISHER] Formatting final signal")
    prompt = (
        f"{state['verdict'][:600]}\n\n"
        f"Rewrite into this exact format, two lines only:\n"
        f"Line 1: VERDICT: [copy the exact verdict type from above — "
        f"CONFIRMED or PARTIALLY CONFIRMED or UNCONFIRMED or FALSE]\n"
        f"Line 2: empty\n"
        f"Line 3: One sentence explaining what the sources "
        f"specifically say or do not say about the claim. "
        f"Name the evidence. Be direct.\n"
        f"Nothing else. No preamble. No KEY SOURCE line."
    )
    published = get_llm().invoke(prompt).content[:600]
    log(f"[PUBLISHER] → {published[:80]}")
    return {"published": published}

graph = StateGraph(State)
graph.add_node("Searcher", searcher_node)
graph.add_node("Scanner", scanner_node)
graph.add_node("Verdict", verdict_node)
graph.add_node("Publisher", publisher_node)
graph.set_entry_point("Searcher")
graph.add_edge("Searcher", "Scanner")
graph.add_edge("Scanner", "Verdict")
graph.add_edge("Verdict", "Publisher")
graph.add_edge("Publisher", END)
swarm = graph.compile()

# Cache ONNX models on the persistent volume so they survive restarts without re-downloading
onnx_cache = os.getenv(
    "CHROMA_ONNX_PATH", 
    os.path.join(CHROMA_PATH, "onnx_models")
)
os.makedirs(onnx_cache, exist_ok=True)
os.environ["SENTENCE_TRANSFORMERS_HOME"] = onnx_cache

chroma = chromadb.PersistentClient(
    path=CHROMA_PATH,
    settings=chromadb.Settings(
        anonymized_telemetry=False,
        allow_reset=False,
    )
)  # CLEANED: use constant
collection = chroma.get_or_create_collection(COL_VERDICTS)  # CLEANED: use constant

async def pin_to_ipfs(data: dict) -> str:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                PINATA_PIN_URL,  # CLEANED: use constant
                headers={"Authorization": f"Bearer {PINATA_JWT}"},
                json={"pinataContent": data, "pinataMetadata": {"name": f"crawlconda-{datetime.now(tz=timezone.utc).isoformat()}"}},
                timeout=TIMEOUT_PINATA,  # CLEANED: use constant
            )
            resp.raise_for_status()
            return f"{IPFS_GATEWAY}{resp.json()['IpfsHash']}"  # CLEANED: use constant
    except Exception as e:
        log(f"[IPFS] Pin failed: {e} — verdict stored locally only")
        import hashlib
        fallback_id = "local_" + hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:40]
        return f"{IPFS_GATEWAY}{fallback_id}"  # CLEANED: use constant

async def run_swarm(content: str) -> dict:
    """Run swarm WITH IPFS (for Discord bot)"""
    result = await swarm.ainvoke({"content": content, "sources": "", "scanned": "", "verdict": "", "published": ""})
    result["ipfs"] = await pin_to_ipfs(result)
    doc_id = result["ipfs"].split("/")[-1]
    collection.upsert(
        ids=[doc_id],
        documents=[json.dumps(result)],
        metadatas=[{
            "claim_key": "",
            "timestamp": datetime.now(tz=timezone.utc).isoformat()
        }]
    )
    return result

async def run_swarm_without_ipfs(content: str) -> dict:
    """Run swarm WITHOUT IPFS (for API - IPFS happens in background)"""
    result = await swarm.ainvoke({"content": content, "sources": "", "scanned": "", "verdict": "", "published": ""})
    # NO IPFS upload here - API will handle it in background
    return result

VERDICT_EMOJI = {"CONFIRMED": "✅", "PARTIALLY CONFIRMED": "🟡", "UNCONFIRMED": "⚠️", "FALSE": "❌"}

VERDICT_COLOR = {
    "CONFIRMED":           0x22c55e,
    "PARTIALLY CONFIRMED": 0xeab308,
    "UNCONFIRMED":         0xf97316,
    "FALSE":               0xef4444,
}

# CLEANED: VERDICT_ORDER defined once at module level, used everywhere
VERDICT_ORDER = [
    "PARTIALLY CONFIRMED",
    "UNCONFIRMED",
    "CONFIRMED",
    "FALSE"
]

def build_verdict_embed(result: dict) -> discord.Embed:
    published = result["published"][:600]
    # CLEANED: use module-level VERDICT_ORDER constant
    verdict_key = next((k for k in VERDICT_ORDER if k in published.upper()), "UNCONFIRMED")
    emoji       = VERDICT_EMOJI[verdict_key]
    color       = VERDICT_COLOR[verdict_key]

    # Strip the "VERDICT: ..." header line — keep only the 2-sentence summary
    summary_lines = [l for l in published.splitlines() if "VERDICT:" not in l.upper()]
    summary = " ".join(summary_lines).strip()[:500]

    embed = discord.Embed(
        title=f"{emoji}  {verdict_key}",
        description=summary,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Claim", value=result.get("content", "")[:300], inline=False)

    # Top 3 sources as a numbered list - TRUNCATE to fit 1024 char limit
    source_lines = []
    if "|||" in result["sources"]:
        for entry in result["sources"].split("|||")[:3]:
            parts = entry.split("||")
            if len(parts) >= 3:
                title, link = parts[0].strip()[:60], parts[1].strip()
                if title and link:
                    source_lines.append(f"{len(source_lines)+1}. [{title}]({link})")
    sources_text = "\n".join(source_lines) if source_lines else "No sources matched."
    embed.add_field(
        name="Sources",
        value=sources_text[:1020],  # Discord limit is 1024 chars per field
        inline=False,
    )
    
    # CLEANED: use module-level WEB_URL constant
    ipfs_hash = result.get("ipfs_hash", result.get("ipfs", "").split("/")[-1])
    
    embed.add_field(
        name="Archived",
        value=f"[IPFS Record]({result['ipfs']}) · [Web View]({WEB_URL}/#/v/{ipfs_hash})",  # CLEANED: use constant
        inline=False,
    )
    embed.set_footer(text="CrawlConda · Ground Truth Engine")
    return embed

# message_id → ipfs_hash, tracked for reaction voting
pending_votes: dict[int, str] = {}

votes_col = chroma.get_or_create_collection(COL_VOTES)  # CLEANED: use constant

def record_vote(ipfs_hash: str, user_id: str, vote: str):
    vote_id = f"{ipfs_hash}:{user_id}"
    existing = votes_col.get(ids=[vote_id])
    if existing["ids"]:
        votes_col.update(
            ids=[vote_id], 
            documents=[vote], 
            metadatas=[{"ipfs_hash": ipfs_hash, 
                        "user_id": user_id, "vote": vote}]
        )
    else:
        votes_col.add(
            ids=[vote_id], 
            documents=[vote], 
            metadatas=[{"ipfs_hash": ipfs_hash, 
                        "user_id": user_id, "vote": vote}]
        )
    log(f"[VOTE] {vote} on {ipfs_hash[:16]}... by {user_id}")
    # recalculate totals and broadcast to all web clients
    all_votes = votes_col.get(where={"ipfs_hash": ipfs_hash})
    up   = sum(1 for v in all_votes["metadatas"] if v["vote"] == "up")
    down = sum(1 for v in all_votes["metadatas"] if v["vote"] == "down")
    # BUG 3 FIX: single vote_update broadcast with all data
    _broadcast({
        "type": "vote_update",
        "data": {
            "ipfs_hash":        ipfs_hash,
            "human_upvotes":    up,
            "human_downvotes":  down,
            "vote":             vote,
            "source":           "discord",
            "ts":               datetime.now(tz=timezone.utc).isoformat()
        }
    })

async def post_to_verified_channel(result: dict):
    """Post every verdict to the public #verified channel."""
    if not VERIFIED_CHANNEL_ID:
        return
    try:
        channel = bot.get_channel(VERIFIED_CHANNEL_ID)
        if not channel:
            channel = await bot.fetch_channel(VERIFIED_CHANNEL_ID)
        embed = build_verdict_embed(result)
        msg   = await channel.send(embed=embed)
        # enable voting reactions on auto-posts too
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        pending_votes[msg.id] = result.get("ipfs_hash", 
            result.get("ipfs","").split("/")[-1])
    except Exception as e:
        log(f"[VERIFIED_CHANNEL] Failed to post: {e}")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ CrawlConda bot live as {bot.user}")

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    ipfs_hash = pending_votes.get(payload.message_id)
    if not ipfs_hash:
        return
    emoji = str(payload.emoji)
    if emoji == "👍":
        record_vote(ipfs_hash, str(payload.user_id), "up")
    elif emoji == "👎":
        record_vote(ipfs_hash, str(payload.user_id), "down")
    # Evict oldest entries if dict exceeds 500 entries
    if len(pending_votes) > 500:
        oldest_keys = list(pending_votes.keys())[:100]
        for k in oldest_keys:
            del pending_votes[k]

@bot.command()
async def verify(ctx, *, text: str):
    log(f"[REQUEST] '{text[:80]}' from {ctx.author} in #{ctx.channel}")
    
    # Create embed with progress tracker
    embed = discord.Embed(
        title="🔍 Verifying Claim",
        description=text[:300],
        color=0x7c6af7
    )
    embed.add_field(name="Progress", value="⟳ Expanding query...", inline=False)
    embed.set_footer(text="CrawlConda · ~26s remaining")
    status = await ctx.send(embed=embed)
    
    try:
        # Progress updates
        steps = [
            ("📡 Scanning 34 sources...", 3, 23),
            ("🧠 Extracting facts...", 8, 15),
            ("⚖️ Cross-referencing sources...", 13, 10),
            ("✅ Issuing verdict...", 17, 6),
            ("📦 Archiving to IPFS...", 20, 3)
        ]
        
        async def update_progress(step_text, delay, remaining):
            await asyncio.sleep(delay)
            embed.set_field_at(0, name="Progress", value=step_text, inline=False)
            embed.set_footer(text=f"CrawlConda · ~{remaining}s remaining")
            try:
                await status.edit(embed=embed)
            except:
                pass
        
        # Start progress updates in background
        progress_tasks = []
        for step_text, delay, remaining in steps:
            task = asyncio.create_task(update_progress(step_text, delay, remaining))
            progress_tasks.append(task)

        
        # BUG 5 FIX: timeout wrapper to prevent Discord WebSocket drops
        try:
            raw = await asyncio.wait_for(
                swarm.ainvoke(
                    {"content": text, "sources": "", "scanned": "", "verdict": "", "published": ""}
                ),
                timeout=120.0
            )
        except asyncio.TimeoutError:
            # Cancel progress tasks
            for task in progress_tasks:
                task.cancel()
            embed.color = 0xef4444
            embed.set_field_at(0, name="Status", value="⚠️ Timed out after 2 minutes", inline=False)
            embed.set_footer(text="Try a more specific claim")
            await status.edit(embed=embed)
            return
        raw["ipfs"] = await pin_to_ipfs(raw)
        raw["content"] = text
        doc_id = raw["ipfs"].split("/")[-1]
        from api import normalize_claim
        _ck = normalize_claim(text)
        collection.upsert(
            ids=[doc_id],
            documents=[json.dumps({**raw, "claim": text})],
            metadatas=[{
                "claim_key": _ck,
                "timestamp": datetime.now(tz=timezone.utc).isoformat()
            }]
        )

        # Cancel progress tasks
        for task in progress_tasks:
            task.cancel()

        # SSE broadcast
        verdict_line = next((l for l in raw["published"].splitlines() if "VERDICT" in l.upper()), "")
        # CLEANED: use module-level VERDICT_ORDER constant
        verdict_key  = next((k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED")
        _broadcast({"type": "new_verdict", "data": {
            "claim": text, "verdict": verdict_key, "emoji": VERDICT_EMOJI[verdict_key],
            "summary": raw["published"], "ipfs_hash": doc_id, "ipfs_url": raw["ipfs"],
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "source": "discord",
        }})

        log(f"[DONE] IPFS: {doc_id}")
        embed = build_verdict_embed(raw)
        try:
            await status.delete()
        except Exception:
            pass
        verdict_msg = await ctx.send(embed=embed)
        pending_votes[verdict_msg.id] = doc_id
        await verdict_msg.add_reaction("👍")
        await verdict_msg.add_reaction("👎")
        
        # Auto-post to #verified if this isn't already the verified channel
        if ctx.channel.id != VERIFIED_CHANNEL_ID:
            asyncio.create_task(post_to_verified_channel({
                **raw,
                "content": text,
                "ipfs_hash": doc_id,
            }))
    except Exception as e:
        log(f"[ERROR] {e}")
        # Cancel progress tasks
        for task in progress_tasks:
            task.cancel()
        embed.color = 0xef4444
        embed.set_field_at(0, name="Status", value="⚠️ Something went wrong", inline=False)
        embed.set_footer(text="Please try again")
        await status.edit(embed=embed)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
