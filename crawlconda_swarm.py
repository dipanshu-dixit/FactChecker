from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from typing import TypedDict
from functools import lru_cache
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
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
PINATA_JWT = os.getenv("PINATA_JWT")

llm = ChatOpenAI(
    model="grok-4-1-fast-reasoning",
    temperature=0,
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
    max_tokens=600,
    max_retries=1,
)

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
    google_rss = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
    feeds = [google_rss] + RSS_FEEDS
    hits = []
    for url in feeds:
        domain = url.split("/")[2]
        name = SOURCE_NAMES.get(domain, domain)
        try:
            feed = feedparser.parse(url)
            matched = 0
            for entry in feed.entries[:15]:
                if "published_parsed" in entry and time.time() - time.mktime(entry.published_parsed) > 86400 * 30:
                    continue
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
        import requests
        from bs4 import BeautifulSoup
        q = requests.utils.quote(query)
        resp = requests.get(
            f"https://lite.duckduckgo.com/lite/?q={q}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=8
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
    return llm.invoke(prompt).content.strip()[:200]

@lru_cache(maxsize=64)
def cached_search(query: str) -> str:
    return search_news(query)

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
    count = len(sources.split("|||")) if "|||" in sources else 0
    log(f"[SEARCHER] Done — {count} sources collected")
    return {"sources": sources}

def scanner_node(state: State):
    log("[SCANNER] Extracting key facts")
    plain = sources_for_llm(state["sources"])
    prompt = (
        f"Claim: {state['content'][:300]}\n\n"
        f"News sources retrieved:\n{plain[:2500]}\n\n"
        f"Extract ONLY facts that are explicitly stated in the sources above. "
        f"Do NOT add any outside knowledge. If a source headline or description mentions an attack, damage, strike, or event — state it as a fact. "
        f"Max 4 bullet points."
    )
    scanned = llm.invoke(prompt).content[:600]
    log(f"[SCANNER] → {scanned[:120]}")
    return {"scanned": scanned}

def verdict_node(state: State):
    log("[VERDICT] Analysing facts")
    plain = sources_for_llm(state["sources"])
    prompt = (
        f"You are a strict news fact-checker. Your ONLY job is to check if the claim is supported by the sources.\n\n"
        f"Claim: {state['content'][:300]}\n\n"
        f"Facts extracted from sources:\n{state['scanned'][:800]}\n\n"
        f"Full sources:\n{plain[:2500]}\n\n"
        f"Rules:\n"
        f"- If sources explicitly report the event, attack, or situation described in the claim → CONFIRMED\n"
        f"- If sources partially support the claim but key details differ → PARTIALLY CONFIRMED\n"
        f"- If sources exist but do NOT mention the claim at all → UNCONFIRMED\n"
        f"- If sources explicitly contradict the claim → FALSE\n"
        f"- NEVER say unconfirmed just because you personally doubt it. Go by what the sources say.\n"
        f"- Quote the exact headline that supports your verdict.\n\n"
        f"Respond in exactly this format:\n"
        f"VERDICT: [CONFIRMED / PARTIALLY CONFIRMED / UNCONFIRMED / FALSE]\n"
        f"REASONING: [1-2 sentences citing the source headline]\n"
        f"KEY SOURCE: [exact headline]"
    )
    verdict = llm.invoke(prompt).content[:600]
    log(f"[VERDICT] → {verdict[:120]}")
    return {"verdict": verdict}

def publisher_node(state: State):
    log("[PUBLISHER] Formatting final signal")
    prompt = (
        f"{state['verdict'][:600]}\n\n"
        f"Rewrite the above into a clean Discord message with exactly:\n"
        f"Line 1: VERDICT: [CONFIRMED / PARTIALLY CONFIRMED / UNCONFIRMED / FALSE]\n"
        f"Line 2: empty\n"
        f"Line 3: Reasoning in 2 sentences max, citing the source.\n"
        f"Nothing else."
    )
    published = llm.invoke(prompt).content[:600]
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

chroma = chromadb.PersistentClient(path="./crawlconda_data")
collection = chroma.get_or_create_collection("verified_crawlconda")

async def pin_to_ipfs(data: dict) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.pinata.cloud/pinning/pinJSONToIPFS",
            headers={"Authorization": f"Bearer {PINATA_JWT}"},
            json={"pinataContent": data, "pinataMetadata": {"name": f"crawlconda-{datetime.now(tz=timezone.utc).isoformat()}"}},  
            timeout=30,
        )
        resp.raise_for_status()
        return f"https://gateway.pinata.cloud/ipfs/{resp.json()['IpfsHash']}"

async def run_swarm(content: str) -> dict:
    result = await swarm.ainvoke({"content": content, "sources": "", "scanned": "", "verdict": "", "published": ""})
    result["ipfs"] = await pin_to_ipfs(result)
    doc_id = result["ipfs"].split("/")[-1]
    collection.add(documents=[json.dumps(result)], ids=[doc_id])
    return result

VERDICT_EMOJI = {"CONFIRMED": "✅", "PARTIALLY CONFIRMED": "🟡", "UNCONFIRMED": "⚠️", "FALSE": "❌"}

def format_discord_msg(result: dict) -> str:
    published = result["published"][:600]
    emoji = next((v for k, v in VERDICT_EMOJI.items() if k in published.upper()), "🔍")
    source_lines = []
    if "|||" in result["sources"]:
        for entry in result["sources"].split("|||")[:3]:
            parts = entry.split("||")
            if len(parts) >= 3:
                title, link, src = parts[0].strip(), parts[1].strip(), parts[2].strip()
                if title and link:
                    source_lines.append(f"• [{title[:80]}]({link}) — {src}")
    sources_block = "\n".join(source_lines) if source_lines else "⚠️ No sources matched."
    ipfs_hash = result['ipfs'].split('/')[-1]
    return (
        f"## {emoji} CrawlConda Verdict\n"
        f"{published}\n\n"
        f"**Sources ({len(source_lines)}):**\n{sources_block}\n\n"
        f"🌐 [IPFS Audit Record]({result['ipfs']}) `{ipfs_hash[:16]}...`"
    )

# message_id → ipfs_hash, tracked for reaction voting
pending_votes: dict[int, str] = {}

votes_col = chroma.get_or_create_collection("human_votes")

def record_vote(ipfs_hash: str, user_id: str, vote: str):
    vote_id = f"{ipfs_hash}:{user_id}"
    existing = votes_col.get(ids=[vote_id])
    if existing["ids"]:
        votes_col.update(ids=[vote_id], documents=[vote], metadatas=[{"ipfs_hash": ipfs_hash, "user_id": user_id, "vote": vote}])
    else:
        votes_col.add(ids=[vote_id], documents=[vote], metadatas=[{"ipfs_hash": ipfs_hash, "user_id": user_id, "vote": vote}])
    log(f"[VOTE] {vote} on {ipfs_hash[:16]}... by {user_id}")

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

@bot.command()
async def verify(ctx, *, text: str):
    log(f"[REQUEST] '{text[:80]}' from {ctx.author} in #{ctx.channel}")
    status = await ctx.send("🔍 **Searching** 7 sources...")
    try:
        result = await run_swarm(text)
        await status.edit(content="📌 **Pinning** to IPFS...")
        log(f"[DONE] IPFS: {result['ipfs'].split('/')[-1]}")
        await status.edit(content=format_discord_msg(result))
        ipfs_hash = result["ipfs"].split("/")[-1]
        pending_votes[status.id] = ipfs_hash
        await status.add_reaction("👍")
        await status.add_reaction("👎")
    except Exception as e:
        log(f"[ERROR] {e}")
        await status.edit(content="⚠️ Something went wrong. Please try again.")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
