from fastapi import FastAPI, HTTPException, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
from collections import defaultdict, deque
import chromadb
import json
import asyncio
import httpx
import time
import re
import os


def normalize_claim(claim: str) -> str:
    claim = claim.lower().strip()
    claim = re.sub(r"[^\w\s]", "", claim)   # strip punctuation
    claim = re.sub(r"\s+", " ", claim)       # collapse whitespace
    return claim

from sse_starlette.sse import EventSourceResponse
from crawlconda_swarm import run_swarm, VERDICT_EMOJI

DISCORD_VERIFIED_WEBHOOK = os.getenv("DISCORD_VERIFIED_WEBHOOK", "")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")
WEB_URL = os.getenv("WEB_URL", "https://fact-checker-teal.vercel.app").strip()  # CLEANED: read once at module level

# ── Constants ──────────────────────────────────────────────────────────────────
CHROMA_PATH        = os.getenv("CHROMA_PATH", "/app/crawlconda_data")  # CLEANED: Railway volume path
COL_VERDICTS       = "verified_crawlconda"
COL_VOTES          = "human_votes"
TIMEOUT_WEBHOOK    = 10
TIMEOUT_IPFS_FETCH = 15
TIMEOUT_PINATA     = 30
TRENDING_CUTOFF_S  = 86400
SSE_QUEUE_MAXSIZE  = 32
SSE_KEEPALIVE_S    = 25
RATE_LIMIT         = 5
RATE_WINDOW        = 3600
CACHE_WINDOW       = 24 * 3600

# Verdict extraction order — check longer strings first to avoid substring matches
VERDICT_ORDER = [
    "PARTIALLY CONFIRMED",
    "UNCONFIRMED",
    "CONFIRMED",
    "FALSE"
]

app = FastAPI(title="CrawlConda API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
verdicts_col = chroma.get_or_create_collection(COL_VERDICTS)  # CLEANED: use constant
votes_col = chroma.get_or_create_collection(COL_VOTES)  # CLEANED: use constant

# ── Rate limiter ──────────────────────────────────────────────────────────────
_rate_store: defaultdict[str, list[float]] = defaultdict(list)

# ── SSE broadcast registry ─────────────────────────────────────────────────────
_sse_clients: list[asyncio.Queue] = []

# ── Activity log ───────────────────────────────────────────────────────────────
_activity_log: deque = deque(maxlen=20)


async def broadcast(event: dict):
    """Push an event to every connected SSE client."""
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass


async def post_to_discord_webhook(payload: dict):
    """Send verdict to Discord #verified channel via webhook."""
    if not DISCORD_VERIFIED_WEBHOOK:
        return
    verdict = payload.get("verdict", "UNCONFIRMED")
    colors = {
        "CONFIRMED":           0x22c55e,
        "PARTIALLY CONFIRMED": 0xeab308,
        "UNCONFIRMED":         0xf97316,
        "FALSE":               0xef4444,
    }
    color = colors.get(verdict, 0x555555)
    emoji = {"CONFIRMED":"✅","PARTIALLY CONFIRMED":"🟡",
             "UNCONFIRMED":"⚠️","FALSE":"❌"}.get(verdict,"🔍")
    
    sources = payload.get("sources", [])
    source_lines = "\n".join(
        f"{i+1}. [{s['title'][:80]}]({s['url']})"
        for i, s in enumerate(sources[:3])
    ) or "No sources matched."
    
    summary = payload.get("summary","").strip()
    # strip VERDICT: header line if present
    summary = "\n".join(
        l for l in summary.splitlines() 
        if "VERDICT:" not in l.upper()
    ).strip()[:500]
    
    # BUG 4 FIX: Format timestamp for Discord, omit if invalid
    raw_ts = (payload.get("timestamp") or "").replace("+00:00", "Z")
    
    embed = {
        "title": f"{emoji}  {verdict}",
        "description": summary,
        "color": color,
        "fields": [
            {"name": "Claim", 
             "value": payload.get("claim","")[:300], 
             "inline": False},
            {"name": "Sources", 
             "value": source_lines, 
             "inline": False},
            {"name": "Archived", 
             "value": f"[View permanent record →]({payload.get('ipfs_url','')})", 
             "inline": False},
            {"name": "Signal this", 
             "value": f"[Open on web]({payload.get('web_url','')})",
             "inline": False},
        ],
        "footer": {"text": "CrawlConda · Ground Truth Engine"},
    }
    if raw_ts:
        embed["timestamp"] = raw_ts
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                DISCORD_VERIFIED_WEBHOOK,
                json={"embeds": [embed]},
                timeout=TIMEOUT_WEBHOOK  # CLEANED: use constant
            )
            print(f"[WEBHOOK] {verdict} → {resp.status_code}")  # CLEANED: single log line
    except Exception as e:
        print(f"[WEBHOOK] Failed: {e}")


@app.get("/stream")
async def stream(request: Request):
    """Server-Sent Events endpoint — real-time verdict push to all web clients."""
    q: asyncio.Queue = asyncio.Queue(maxsize=SSE_QUEUE_MAXSIZE)  # CLEANED: use constant
    _sse_clients.append(q)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=SSE_KEEPALIVE_S)  # CLEANED: use constant
                    yield {"event": event["type"], "data": json.dumps(event["data"])}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}   # keep-alive heartbeat
        finally:
            try:
                _sse_clients.remove(q)
            except ValueError:
                pass

    return EventSourceResponse(generator())


@app.post("/internal/broadcast")
async def internal_broadcast(
    event: dict,
    x_internal_secret: str = Header(default="")
):
    """Internal endpoint for bot process to push SSE events."""
    if INTERNAL_SECRET and x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    await broadcast(event)
    
    ts    = datetime.now(tz=timezone.utc).isoformat()
    data  = event.get("data", {})
    etype = event.get("type", "")
    
    try:
        if etype == "new_verdict":
            _activity_log.append({
                "type":    "verify",
                "claim":   data.get("claim", ""),
                "verdict": data.get("verdict", "UNCONFIRMED"),
                "source":  "discord",
                "ts":      data.get("timestamp", ts)
            })
            print(f"[ACTIVITY] Discord verdict logged: {data.get('claim','')[:50]}")
        elif etype == "vote_update":
            _activity_log.append({
                "type":      "vote",
                "ipfs_hash": data.get("ipfs_hash", ""),
                "vote":      data.get("vote", "signal"),
                "source":    "discord",
                "ts":        ts
            })
            print(f"[ACTIVITY] Discord vote logged: {data.get('vote','')} on {data.get('ipfs_hash','')[:16]}")
    except Exception as e:
        print(f"[ACTIVITY] Failed to log: {e}")
    
    return {"ok": True}


# ── Models ─────────────────────────────────────────────────────────────────────
class VoteRequest(BaseModel):
    vote: str       # "up" or "down"
    user_id: str


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/verify")
async def verify(claim: str, request: Request):
    # ── 1. Minimum length ──────────────────────────────────────────────────────
    if len(claim.strip()) < 8:
        raise HTTPException(status_code=400, detail="Claim too short. Please enter at least 8 characters.")

    # ── 2. Rate limit ──────────────────────────────────────────────────────────
    ip = request.headers.get(
        "x-forwarded-for", request.client.host
    ).split(",")[0].strip()
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]  # CLEANED: use constant
    # Periodically purge IPs with no recent requests
    if len(_rate_store) > 1000:
        stale = [k for k, v in _rate_store.items() if not v]
        for k in stale:
            del _rate_store[k]
    if len(_rate_store[ip]) >= RATE_LIMIT:  # CLEANED: use constant
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 5 verifications per hour per IP.")
    _rate_store[ip].append(now)

    # ── 3. Duplicate-claim cache (metadata index lookup — O(1)) ───────────────
    claim_key = normalize_claim(claim)
    try:
        cached_results = verdicts_col.get(
            where={"claim_key": {"$eq": claim_key}},
            limit=1,
        )
        if cached_results["ids"]:
            doc_id  = cached_results["ids"][0]
            cached  = json.loads(cached_results["documents"][0])
            meta    = cached_results["metadatas"][0] if cached_results["metadatas"] else {}
            cached_ts = meta.get("timestamp") or cached.get("timestamp", "")
            if cached_ts:
                age = now - datetime.fromisoformat(
                    cached_ts.replace("Z", "+00:00")
                ).timestamp()
                if age < CACHE_WINDOW:  # CLEANED: use constant
                    votes = votes_col.get(where={"ipfs_hash": doc_id})
                    up   = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
                    down = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
                    return {**cached, "ipfs_hash": doc_id,
                            "human_upvotes": up, "human_downvotes": down,
                            "cached": True}
    except Exception as e:
        print(f"[CACHE] miss — {e}")  # CLEANED: add log to silent except

    # ── 4. Full pipeline ───────────────────────────────────────────────────────
    result = await run_swarm(claim)
    ipfs_hash = result["ipfs"].split("/")[-1]
    verdict_line = next(
        (l for l in result["published"].splitlines() if "VERDICT" in l.upper()), ""
    )
    verdict_key = next(
        (k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED"
    )
    sources = [
        {"title": p[0], "url": p[1], "source": p[2]}
        for entry in result["sources"].split("|||")[:8]
        if len(p := entry.split("||")) >= 3
    ]
    ts = datetime.now(tz=timezone.utc).isoformat()
    payload = {
        "claim": claim,
        "verdict": verdict_key,
        "emoji": VERDICT_EMOJI[verdict_key],
        "summary": result["published"],
        "sources": sources,
        "ipfs_hash": ipfs_hash,
        "ipfs_url": result["ipfs"],
        "timestamp": ts,
        "claim_key": claim_key,
    }
    # update ChromaDB metadata so future cache lookups hit the index
    try:
        verdicts_col.update(
            ids=[ipfs_hash],
            metadatas=[{"claim_key": claim_key, "timestamp": ts}],
        )
    except Exception:
        try:
            verdicts_col.upsert(
                ids=[ipfs_hash],
                documents=[json.dumps({**result,
                    "claim": claim,
                    "timestamp": ts,
                    "claim_key": claim_key
                })],
                metadatas=[{"claim_key": claim_key, "timestamp": ts}],
            )
        except Exception as e:
            print(f"[CACHE] Failed to write claim_key: {e}")
    # log activity
    _activity_log.append({"type": "verify", "claim": claim, "verdict": verdict_key, "ts": ts})
    # set web_url BEFORE broadcast so SSE clients receive it
    payload["web_url"] = f"{WEB_URL}/#/v/{ipfs_hash}"  # CLEANED: use module-level constant
    await broadcast({"type": "new_verdict", "data": payload})
    asyncio.create_task(post_to_discord_webhook(payload))
    return payload


@app.post("/confirm/{ipfs_hash}")
async def confirm(ipfs_hash: str, body: VoteRequest):
    if body.vote not in ("up", "down"):
        raise HTTPException(status_code=400, detail="vote must be 'up' or 'down'")
    if not body.user_id or len(body.user_id) > 128:
        raise HTTPException(status_code=400, detail="user_id must be 1-128 characters.")
    if ":" in body.user_id:
        raise HTTPException(status_code=400, detail="user_id cannot contain ':'")
    vote_id = f"{ipfs_hash}:{body.user_id}"
    existing = votes_col.get(ids=[vote_id])
    if existing["ids"]:
        votes_col.update(
            ids=[vote_id],
            documents=[body.vote],
            metadatas=[{"ipfs_hash": ipfs_hash, "user_id": body.user_id, "vote": body.vote}],
        )
        status = "updated"
    else:
        votes_col.add(
            ids=[vote_id],
            documents=[body.vote],
            metadatas=[{"ipfs_hash": ipfs_hash, "user_id": body.user_id, "vote": body.vote}],
        )
        status = "recorded"
    
    # recalculate totals and broadcast
    all_votes = votes_col.get(where={"ipfs_hash": ipfs_hash})
    up   = sum(1 for v in all_votes["metadatas"] if v["vote"] == "up")
    down = sum(1 for v in all_votes["metadatas"] if v["vote"] == "down")
    
    # log activity
    ts = datetime.now(tz=timezone.utc).isoformat()
    _activity_log.append({"type": "vote", "ipfs_hash": ipfs_hash, "vote": body.vote, "ts": ts})
    
    await broadcast({
        "type": "vote_update",
        "data": {
            "ipfs_hash": ipfs_hash,
            "human_upvotes": up,
            "human_downvotes": down
        }
    })
    return {"status": status, "vote": body.vote}


@app.get("/verdict/{ipfs_hash}")
def get_verdict(ipfs_hash: str):
    results = verdicts_col.get(ids=[ipfs_hash])
    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Verdict not found")
    data = json.loads(results["documents"][0])
    votes = votes_col.get(where={"ipfs_hash": ipfs_hash})
    up   = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
    down = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
    # parse raw pipe-delimited sources into [{title, url, source}] array
    raw_sources = data.get("sources", "")
    if isinstance(raw_sources, str) and "|||" in raw_sources:
        sources = [
            {"title": p[0], "url": p[1], "source": p[2]}
            for entry in raw_sources.split("|||")[:8]
            if len(p := entry.split("||")) >= 3
        ]
    elif isinstance(raw_sources, list):
        sources = raw_sources
    else:
        sources = []
    # extract verdict key and emoji from published text
    published = data.get("published", "")
    verdict_line = next((l for l in published.splitlines() if "VERDICT" in l.upper()), "")
    verdict_key  = next((k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED")
    return {
        **data,
        "claim":          data.get("claim") or data.get("content", ""),
        "verdict":        verdict_key,
        "emoji":          VERDICT_EMOJI[verdict_key],
        "summary":        published,
        "sources":        sources,
        "ipfs_hash":      ipfs_hash,
        "ipfs_url":       data.get("ipfs", ""),
        "human_upvotes":  up,
        "human_downvotes": down,
    }


@app.get("/verdicts")
def list_verdicts(limit: int = Query(default=20, le=200)):
    results = verdicts_col.get(limit=limit)
    out = []
    for doc_id, doc in zip(results["ids"], results["documents"]):
        try:
            data = json.loads(doc)
            ipfs_hash = data.get("ipfs", "").split("/")[-1] or doc_id
            votes = votes_col.get(where={"ipfs_hash": ipfs_hash}) if ipfs_hash else {"metadatas": []}
            up = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
            down = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
            out.append({
                "id": doc_id,
                "ipfs_hash": ipfs_hash,
                "human_upvotes": up,
                "human_downvotes": down,
                "claim": data.get("claim") or data.get("content", ""),
                **data,
            })
        except Exception:
            continue
    return {"verdicts": out, "count": len(out)}


@app.get("/trending")
def trending():
    """Top 5 verdicts by combined votes in the last 24 hours."""
    cutoff = datetime.now(tz=timezone.utc).timestamp() - TRENDING_CUTOFF_S  # CLEANED: use constant
    results = verdicts_col.get(limit=500)
    scored = []
    for doc_id, doc, meta in zip(
        results["ids"],
        results["documents"],
        results["metadatas"] or [{}] * len(results["ids"])
    ):
        try:
            data = json.loads(doc)
            ts   = data.get("timestamp") or meta.get("timestamp", "")
            if ts:
                age = datetime.fromisoformat(
                    ts.replace("Z", "+00:00")).timestamp()
                if age < cutoff:
                    continue
            ipfs_hash = data.get("ipfs","").split("/")[-1] or doc_id
            votes = votes_col.get(where={"ipfs_hash": ipfs_hash})
            score = len(votes["metadatas"])
            if score > 0:
                up   = sum(1 for v in votes["metadatas"] if v["vote"]=="up")
                down = sum(1 for v in votes["metadatas"] if v["vote"]=="down")
                scored.append({
                    "claim":    data.get("claim") or data.get("content", ""),
                    "verdict":  data.get("verdict",""),
                    "ipfs_hash": ipfs_hash,
                    "human_upvotes":   up,
                    "human_downvotes": down,
                    "total_votes": score
                })
        except Exception:
            continue
    scored.sort(key=lambda x: x["total_votes"], reverse=True)
    return {"trending": scored[:5]}


@app.get("/activity")
def get_activity():
    return {"events": list(reversed(_activity_log))}


@app.post("/recover")
async def recover_from_pinata():
    """Rebuild local ChromaDB index from all pins on Pinata."""
    # CLEANED: removed duplicate imports (httpx, os already at top)
    pinata_jwt = os.getenv("PINATA_JWT")
    if not pinata_jwt:
        raise HTTPException(status_code=500, detail="PINATA_JWT not set")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.pinata.cloud/data/pinList?status=pinned&pageLimit=1000&metadata[name]=crawlconda",
            headers={"Authorization": f"Bearer {pinata_jwt}"},
            timeout=TIMEOUT_PINATA,  # CLEANED: use constant
        )
        resp.raise_for_status()
        pins = resp.json().get("rows", [])

    recovered, skipped = 0, 0
    async with httpx.AsyncClient() as client:
        for pin in pins:
            ipfs_hash = pin["ipfs_pin_hash"]
            existing = verdicts_col.get(ids=[ipfs_hash])
            if existing["ids"]:
                skipped += 1
                continue
            try:
                r = await client.get(
                    f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}",
                    timeout=TIMEOUT_IPFS_FETCH  # CLEANED: use constant
                )
                data = r.json()
                verdicts_col.add(
                    ids=[ipfs_hash],
                    documents=[json.dumps(data)]
                )
                recovered += 1
            except Exception:
                skipped += 1

    return {"recovered": recovered, "skipped": skipped, "total_pins": len(pins)}