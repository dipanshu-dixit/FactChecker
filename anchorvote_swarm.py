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
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))
PINATA_JWT = os.getenv("PINATA_JWT")

llm = ChatOpenAI(
    model="grok-4-1-fast",
    temperature=0,
    api_key=os.getenv("XAI_API_KEY"),
    base_url="https://api.x.ai/v1",
    max_tokens=350,
    max_retries=1,
)

RSS_FEEDS = [
    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://timesofindia.indiatimes.com/rssfeeds/1898184.cms",
    "https://feeds.skynews.com/feeds/rss/world.xml",
]

class State(TypedDict):
    content: str
    sources: str
    scanned: str
    verdict: str
    published: str

def search_news(query: str) -> str:
    keywords = [w.lower() for w in query.split() if len(w) > 3]
    google_rss = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
    feeds = [google_rss] + RSS_FEEDS
    hits = []
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                if "published_parsed" in entry and time.time() - time.mktime(entry.published_parsed) > 86400 * 2:
                    continue
                text = (entry.get("title", "") + " " + entry.get("summary", "") + " " + entry.get("description", "")).lower()
                match_count = sum(1 for k in keywords if k in text)
                if match_count >= max(1, len(keywords) // 2):
                    desc = entry.get("summary", entry.get("description", ""))[:300]
                    hits.append(f"✅ {entry.title}\n🔗 {entry.link}\n{desc}")
                    if len(hits) >= 6:
                        break
        except Exception as e:
            print(f"Feed error ({url}): {e}")
        if len(hits) >= 6:
            break
    if hits:
        return "\n\n".join(hits)
    # DuckDuckGo fallback
    try:
        import requests
        from bs4 import BeautifulSoup
        q = requests.utils.quote(query + " site:reuters.com OR site:bbc.com OR site:aljazeera.com OR site:bloomberg.com")
        resp = requests.get(f"https://html.duckduckgo.com/html/?q={q}", headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        ddg = [f"✅ {a.get_text()}\n🔗 {a['href']}" for a in soup.find_all("a", class_="result__a")[:5]]
        return "\n\n".join(ddg) if ddg else "No recent matching reports found."
    except Exception:
        return "No recent matching reports found."

def x_search_fallback(query: str) -> str:
    """Pull recent tweets via Nitter RSS — no API key needed."""
    try:
        import requests
        q = requests.utils.quote(query)
        url = f"https://nitter.net/search/rss?q={q}&f=tweets"
        feed = feedparser.parse(url)
        hits = []
        for entry in feed.entries[:5]:
            title = entry.get("title", "")[:200]
            link = entry.get("link", "")
            author = entry.get("author", "unknown")
            hits.append(f"🗨️ {title}\n👤 {author}\n🔗 {link}")
        return "\n\n".join(hits) if hits else ""
    except Exception as e:
        print(f"X/Nitter search error: {e}")
        return ""

@lru_cache(maxsize=64)
def cached_search(query: str) -> str:
    return search_news(query)

def searcher_node(state: State):
    print("🔍 Running Searcher node...")
    sources = cached_search(state["content"])
    if "No recent matching" in sources:
        print("RSS weak — trying Nitter X search...")
        x_results = x_search_fallback(state["content"])
        if x_results:
            sources += "\n\n**From X/Twitter:**\n" + x_results
    print("Search results:", sources[:200])
    return {"sources": sources}

def scanner_node(state: State):
    print("🕵️ Running Scanner node...")
    prompt = f"Claim: {state['content'][:200]}\nSources:\n{state['sources'][:400]}\nList key facts only. Max 3 bullet points."
    scanned = llm.invoke(prompt).content[:350]
    print("Scanned:", scanned[:200])
    return {"scanned": scanned}

def verdict_node(state: State):
    print("⚖️ Running Verdict node...")
    prompt = f"Facts: {state['scanned'][:200]}\nSources:\n{state['sources'][:400]}\nIs this claim CONFIRMED, UNCONFIRMED, or FALSE based on sources? Give verdict + 2 sentence reasoning."
    verdict = llm.invoke(prompt).content[:350]
    print("Verdict:", verdict[:200])
    return {"verdict": verdict}

def publisher_node(state: State):
    print("📤 Running Publisher node...")
    prompt = f"Verdict: {state['verdict'][:200]}\nSources:\n{state['sources'][:300]}\nWrite a final 3-part anchor signal: 1) Verdict line 2) Reasoning 3) Sources list with links."
    published = llm.invoke(prompt).content[:500]
    print("Published:", published[:200])
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

chroma = chromadb.PersistentClient(path="./anchor_data")
collection = chroma.get_or_create_collection("verified_anchors")

async def pin_to_ipfs(data: dict) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.pinata.cloud/pinning/pinJSONToIPFS",
            headers={"Authorization": f"Bearer {PINATA_JWT}"},
            json={"pinataContent": data, "pinataMetadata": {"name": f"anchor-{datetime.now(tz=timezone.utc).isoformat()}"}},
            timeout=30,
        )
        resp.raise_for_status()
        return f"https://gateway.pinata.cloud/ipfs/{resp.json()['IpfsHash']}"

async def run_swarm(content: str) -> dict:
    result = await swarm.ainvoke({"content": content, "sources": "", "scanned": "", "verdict": "", "published": ""})
    collection.add(documents=[json.dumps(result)], ids=[str(datetime.now(tz=timezone.utc))])
    result["ipfs"] = await pin_to_ipfs(result)
    return result

def format_discord_msg(result: dict) -> str:
    sources = result["sources"] if "No matching" not in result["sources"] else "⚠️ No recent RSS sources matched — verdict based on claim text only."
    return (
        f"## 🔍 AnchorVote Signal\n"
        f"{result['published'][:900]}\n\n"
        f"**Sources searched:**\n{sources[:700]}\n\n"
        f"🌐 IPFS: {result['ipfs']}"
    )

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ AnchorVote bot live as {bot.user}")

@bot.command()
async def verify(ctx, *, text: str):
    await ctx.send("🔍 Searching sources + running swarm...")
    result = await run_swarm(text)
    content = format_discord_msg(result)
    # Split if over Discord's 2000 char limit
    for chunk in [content[i:i+1900] for i in range(0, len(content), 1900)]:
        await ctx.send(chunk)

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
