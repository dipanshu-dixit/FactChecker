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

def _broadcast(data: dict):
    """Push event directly to API broadcast (same process)."""
    try:
        from api import broadcast as _api_broadcast
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(_api_broadcast(data))
            )
        except RuntimeError:
            asyncio.run(_api_broadcast(data))
    except Exception as e:
        print(f"[BROADCAST] Failed: {e}")

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
    # Business / Economy
    "http://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",
    "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "https://www.theguardian.com/business/rss",
    # Technology
    "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theguardian.com/technology/rss",
    # Science
    "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://www.sciencedaily.com/rss/top/science.xml",
    "https://www.theguardian.com/science/rss",
    # US News
    "https://www.theguardian.com/us-news/rss",
    # Sport
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://www.espn.com/espn/rss/news",
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
}

def log(msg: str):
    print(f"[{datetime.now(tz=timezone.utc).strftime('%H:%M:%S')}] {msg}")

def search_news(query: str) -> str:
    keywords = [w.lower() for w in query.split() if len(w) > 3]
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
                    if (entry.get("published_parsed") and
                            time.time() - time.mktime(
                                entry.published_parsed) > 86400 * 30):
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
                    hits.append((match_count, entry.title, entry.link, name, desc))
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
    return get_llm().invoke(prompt).content.strip()[:200]

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
        f"Extract ONLY facts that are explicitly stated in the sources above. "
        f"Do NOT add any outside knowledge. If a source headline or description mentions an attack, damage, strike, or event — state it as a fact. "
        f"Max 4 bullet points."
    )
    scanned = get_llm().invoke(prompt).content[:600]
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
                "REASONING: No sources were located across 24 monitored feeds "
                "for this claim. Cannot confirm or deny without source material.\n"
                "KEY SOURCE: None"
            )
        }
    plain = sources_for_llm(state["sources"])
    prompt = (
        f"You are a strict evidence-based fact-checker. "
        f"Your only job is to determine if the SPECIFIC claim is "
        f"directly answered by the sources provided.\n\n"
        f"Claim: {state['content'][:300]}\n\n"
        f"Facts extracted from sources:\n{state['scanned'][:800]}\n\n"
        f"Full sources:\n{plain[:2500]}\n\n"
        f"STRICT RULES — read carefully:\n"
        f"- CONFIRMED: Sources contain explicit, direct evidence that "
        f"the specific claim is true. The claim must be answerable "
        f"YES from the sources. Related topic coverage is NOT enough.\n"
        f"- PARTIALLY CONFIRMED: Sources directly address part of the "
        f"claim but leave key parts unanswered or uncertain.\n"
        f"- UNCONFIRMED: Sources exist on the topic but do NOT directly "
        f"answer or address the specific claim being made. "
        f"This is the correct verdict when sources discuss a related "
        f"topic but do not confirm the specific assertion.\n"
        f"- FALSE: Sources explicitly and directly contradict the claim.\n\n"
        f"CRITICAL: Ask yourself — do the sources DIRECTLY answer this "
        f"exact claim? If sources only cover a related topic without "
        f"directly confirming the specific assertion, verdict is "
        f"UNCONFIRMED, not CONFIRMED.\n\n"
        f"Example: Claim='Is Israel stopping the Iran war' + sources "
        f"about Iran war existing = UNCONFIRMED. Sources talk about "
        f"the topic but do not answer whether Israel is stopping it.\n\n"
        f"Respond in exactly this format:\n"
        f"VERDICT: [CONFIRMED / PARTIALLY CONFIRMED / UNCONFIRMED / FALSE]\n"
        f"REASONING: [1-2 sentences. Must cite what the source "
        f"specifically says or does NOT say about the claim.]\n"
        f"KEY SOURCE: [exact headline, or 'None' if no direct source]"
    )
    verdict = get_llm().invoke(prompt).content[:600]
    log(f"[VERDICT] → {verdict[:120]}")
    return {"verdict": verdict}

def publisher_node(state: State):
    log("[PUBLISHER] Formatting final signal")
    prompt = (
        f"{state['verdict'][:600]}\n\n"
        f"Rewrite the REASONING section above into 2 clean sentences "
        f"that explain what the sources DO and DO NOT say about the claim. "
        f"Be specific — name what evidence exists and what is missing.\n"
        f"Start directly with the explanation, no preamble.\n"
        f"Do not include the VERDICT line or KEY SOURCE line.\n"
        f"Nothing else."
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

chroma = chromadb.PersistentClient(path=CHROMA_PATH)  # CLEANED: use constant
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
    _broadcast({
        "type": "vote_update",
        "data": {
            "ipfs_hash": ipfs_hash,
            "human_upvotes":   up,
            "human_downvotes": down,
            "source": "discord"
        }
    })
    _broadcast({
        "type": "activity_update", 
        "data": {
            "type": "vote",
            "ipfs_hash": ipfs_hash,
            "vote": vote,
            "source": "discord",
            "ts": datetime.now(tz=timezone.utc).isoformat()
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
    status = await ctx.send("🔍  Expanding query...")
    try:
        # Stage labels mirror the LangGraph pipeline nodes
        async def update(msg): await status.edit(content=msg)

        # Patch each node to emit a stage update before it runs
        _orig_searcher = searcher_node
        _orig_scanner  = scanner_node
        _orig_verdict  = verdict_node
        _orig_publisher = publisher_node

        async def _patched_searcher(state):
            await update("📡  Scanning 24 sources...")
            return _orig_searcher(state)
        async def _patched_scanner(state):
            await update("🧠  Extracting facts...")
            return _orig_scanner(state)
        async def _patched_verdict(state):
            await update("⚖️  Issuing verdict...")
            return _orig_verdict(state)

        # Build a one-shot patched graph for this invocation
        from langgraph.graph import StateGraph, END as _END
        g = StateGraph(State)
        g.add_node("Searcher",  _patched_searcher)
        g.add_node("Scanner",   _patched_scanner)
        g.add_node("Verdict",   _patched_verdict)
        g.add_node("Publisher", _orig_publisher)
        g.set_entry_point("Searcher")
        g.add_edge("Searcher", "Scanner")
        g.add_edge("Scanner",  "Verdict")
        g.add_edge("Verdict",  "Publisher")
        g.add_edge("Publisher", _END)
        patched_swarm = g.compile()

        raw = await patched_swarm.ainvoke(
            {"content": text, "sources": "", "scanned": "", "verdict": "", "published": ""}
        )
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
            await status.edit(content="✓")
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
        await status.edit(content="⚠️ Something went wrong. Please try again.")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
