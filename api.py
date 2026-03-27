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
import logging
import hashlib
from typing import Optional, Dict, Tuple
from asyncio import Lock, Event

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def normalize_claim(claim: str) -> str:
    claim = claim.lower().strip()
    claim = re.sub(r"[^\w\s]", "", claim)   # strip punctuation
    claim = re.sub(r"\s+", " ", claim)       # collapse whitespace
    return claim

from sse_starlette.sse import EventSourceResponse
from crawlconda_swarm import run_swarm, run_swarm_without_ipfs, VERDICT_EMOJI
from api_keys import APIKeyManager
from badge_generator import generate_badge_svg, generate_badge_html, generate_badge_markdown

DISCORD_VERIFIED_WEBHOOK = os.getenv("DISCORD_VERIFIED_WEBHOOK", "")
INTERNAL_SECRET = os.getenv("INTERNAL_SECRET", "")
WEB_URL = os.getenv("WEB_URL", "https://fact-checker-teal.vercel.app").strip()
PINATA_JWT = os.getenv("PINATA_JWT")

# ── Constants ──────────────────────────────────────────────────────────────────
CHROMA_PATH        = os.getenv("CHROMA_PATH", "/app/crawlconda_data")
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
IPFS_GATEWAY       = "https://gateway.pinata.cloud/ipfs/"
PINATA_PIN_URL     = "https://api.pinata.cloud/pinning/pinJSONToIPFS"

# 🔥 FIX #2: Request coalescing infrastructure
_inflight_requests: Dict[str, Tuple[Event, Optional[dict]]] = {}
_inflight_lock = Lock()

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

# Initialize API key manager
api_key_manager = APIKeyManager(chroma)

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


# 🔥 FIX #1: Background IPFS upload
async def upload_to_ipfs_async(verdict_hash: str, result: dict, claim: str):
    """Background task: upload to IPFS and update DB"""
    try:
        logger.info(f"[IPFS] Starting upload for {verdict_hash}")
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                PINATA_PIN_URL,
                headers={"Authorization": f"Bearer {PINATA_JWT}"},
                json={
                    "pinataContent": result,
                    "pinataMetadata": {
                        "name": f"crawlconda-{datetime.now(tz=timezone.utc).isoformat()}"
                    }
                },
                timeout=TIMEOUT_PINATA,
            )
            resp.raise_for_status()
            ipfs_url = f"{IPFS_GATEWAY}{resp.json()['IpfsHash']}"
        
        # Update DB with IPFS URL
        try:
            verdicts_col.update(
                ids=[verdict_hash],
                metadatas=[{
                    "ipfs_url": ipfs_url,
                    "status": "archived",
                    "claim_key": normalize_claim(claim),
                    "timestamp": datetime.now(tz=timezone.utc).isoformat()
                }]
            )
        except Exception as e:
            logger.error(f"[IPFS] DB update failed: {e}")
        
        # Broadcast IPFS completion
        await broadcast({
            "type": "ipfs_complete",
            "data": {
                "ipfs_hash": verdict_hash,
                "ipfs_url": ipfs_url
            }
        })
        
        logger.info(f"[IPFS] ✓ Archived {verdict_hash} → {ipfs_url}")
        
    except Exception as e:
        logger.error(f"[IPFS] ✗ Failed for {verdict_hash}: {e}")
        # Verdict still usable without IPFS


async def post_to_discord_webhook(payload: dict):
    """Send verdict to Discord #verified channel via webhook."""
    if not DISCORD_VERIFIED_WEBHOOK:
        return
    
    # Validate required fields
    web_url = payload.get("web_url", "").strip()
    if not web_url:
        logger.warning(f"[WEBHOOK] Skipped - missing web_url")
        return
    
    # 🔥 FIX #1: IPFS URL is optional now (may not be ready yet)
    ipfs_url = payload.get("ipfs_url", "").strip() or "Archiving..."
    
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
        f"{i+1}. [{s['title'][:60]}]({s['url']})"
        for i, s in enumerate(sources[:3])
        if s.get('title') and s.get('url')
    ) or "No sources matched."
    # Discord field limit is 1024 chars
    source_lines = source_lines[:1020]
    
    summary = payload.get("summary","").strip()
    # strip VERDICT: header line if present
    summary = "\n".join(
        l for l in summary.splitlines() 
        if "VERDICT:" not in l.upper()
    ).strip()[:500]
    
    claim = payload.get("claim", "").strip()[:300]
    if not claim:
        claim = "No claim provided"
    
    embed = {
        "title": f"{emoji}  {verdict}",
        "description": summary or "No summary available",
        "color": color,
        "fields": [
            {"name": "Claim", "value": claim, "inline": False},
            {"name": "Sources", "value": source_lines, "inline": False},
            {"name": "Archived", "value": f"[View record]({ipfs_url})", "inline": False},
            {"name": "Vote", "value": f"[Open on web]({web_url})", "inline": False},
        ],
        "footer": {"text": "CrawlConda · Ground Truth Engine"},
    }
    
    # Add timestamp only if valid ISO8601
    raw_ts = payload.get("timestamp", "")
    if raw_ts:
        try:
            # Validate and normalize timestamp
            dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            embed["timestamp"] = dt.isoformat().replace("+00:00", "Z")
        except (ValueError, AttributeError):
            pass  # Skip invalid timestamp
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                DISCORD_VERIFIED_WEBHOOK,
                json={"embeds": [embed]},
                timeout=TIMEOUT_WEBHOOK
            )
            if resp.status_code == 400:
                print(f"[WEBHOOK] 400 Bad Request - Response: {resp.text[:200]}")
            else:
                print(f"[WEBHOOK] {verdict} → {resp.status_code}")
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

class APIKeyRequest(BaseModel):
    name: str
    email: str
    use_case: str = ""  # Optional description


# ── Helper: Extract API key from header ──────────────────────────────────────
def get_api_key(authorization: str = Header(default="")) -> Optional[str]:
    """Extract API key from Authorization header.
    
    Accepts: 'Bearer cc_live_...' or 'cc_live_...'
    """
    if not authorization:
        return None
    
    # Strip 'Bearer ' prefix if present
    if authorization.startswith("Bearer "):
        return authorization[7:].strip()
    
    return authorization.strip() if authorization.startswith("cc_live_") else None


# ── Endpoints ──────────────────────────────────────────────────────────────────
# 🔥 REPLACE THE ENTIRE /verify ENDPOINT IN api.py WITH THIS CODE

@app.get("/verify")
async def verify(claim: str, request: Request, authorization: str = Header(default="")):
    start_time = time.time()
    logger.info(f"[VERIFY] START: {claim[:50]}")
    
    # ── 1. Minimum length ──────────────────────────────────────────────────────
    if len(claim.strip()) < 8:
        raise HTTPException(status_code=400, detail="Claim too short. Please enter at least 8 characters.")

    claim_key = normalize_claim(claim)
    now = time.time()
    
    # ── 2. Check cache FIRST (before rate limit for cached hits) ──────────────
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
                if age < CACHE_WINDOW:
                    votes = votes_col.get(where={"ipfs_hash": doc_id})
                    up   = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
                    down = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
                    logger.info(f"[CACHE] HIT: {claim_key}")
                    return {**cached, "ipfs_hash": doc_id,
                            "human_upvotes": up, "human_downvotes": down,
                            "cached": True}
    except Exception as e:
        logger.warning(f"[CACHE] miss — {e}")

    # ── 3. Rate limiting (AFTER cache check) ──────────────────────────────────
    api_key = get_api_key(authorization)
    if api_key:
        key_meta = api_key_manager.validate_key(api_key)
        if not key_meta:
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        if not api_key_manager.increment_usage(api_key):
            tier = key_meta.get("tier", "free")
            limit = 1000 if tier == "pro" else 100
            raise HTTPException(
                status_code=429,
                detail=f"API key rate limit exceeded. {tier.title()} tier: {limit} requests/day"
            )
        
        logger.info(f"[API_KEY] Request from {key_meta.get('name', 'unknown')}")
    else:
        ip = request.headers.get(
            "x-forwarded-for", request.client.host
        ).split(",")[0].strip()
        _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
        if len(_rate_store) > 1000:
            stale = [k for k, v in _rate_store.items() if not v]
            for k in stale:
                del _rate_store[k]
        if len(_rate_store[ip]) >= RATE_LIMIT:
            raise HTTPException(
                status_code=429, 
                detail="Rate limit exceeded. Max 5 verifications per hour per IP. Get an API key for higher limits."
            )
        _rate_store[ip].append(now)

    # 🔥 FIX #2: REQUEST COALESCING
    async with _inflight_lock:
        if claim_key in _inflight_requests:
            event, result = _inflight_requests[claim_key]
            if result:
                logger.info(f"[COALESCE] Returning cached result: {claim_key}")
                return result
            else:
                logger.info(f"[COALESCE] Waiting for leader: {claim_key}")
        else:
            event = Event()
            _inflight_requests[claim_key] = (event, None)
            logger.info(f"[COALESCE] Starting new request: {claim_key}")
    
    # If we're a follower, wait
    if claim_key in _inflight_requests:
        _, result = _inflight_requests[claim_key]
        if result is None:
            event, _ = _inflight_requests[claim_key]
            await event.wait()
            _, result = _inflight_requests[claim_key]
            if result:
                logger.info(f"[COALESCE] Follower received result: {claim_key}")
                return result
    
    # We're the leader, run the pipeline
    try:
        pipeline_start = time.time()
        logger.info(f"[VERIFY] Running swarm pipeline...")
        
        # 🔥 FIX #1: Call version WITHOUT IPFS
        result = await run_swarm_without_ipfs(claim)
        
        pipeline_time = time.time() - pipeline_start
        logger.info(f"[VERIFY] Pipeline completed in {pipeline_time:.2f}s")
        
        # Generate deterministic hash
        verdict_hash = hashlib.sha256(
            f"{claim}:{result['published']}:{time.time()}".encode()
        ).hexdigest()[:16]
        
        # Extract verdict
        verdict_line = next(
            (l for l in result["published"].splitlines() if "VERDICT" in l.upper()), ""
        )
        verdict_key = next(
            (k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED"
        )
        
        # Parse sources
        sources = [
            {"title": p[0], "url": p[1], "source": p[2]}
            for entry in result["sources"].split("|||")[:8]
            if len(p := entry.split("||")) >= 3
        ]
        
        ts = datetime.now(tz=timezone.utc).isoformat()
        
        # Build payload
        payload = {
            "claim": claim,
            "verdict": verdict_key,
            "emoji": VERDICT_EMOJI[verdict_key],
            "summary": result["published"],
            "sources": sources,
            "ipfs_hash": verdict_hash,
            "ipfs_url": None,  # 🔥 Will be updated by background task
            "timestamp": ts,
            "claim_key": claim_key,
            "status": "processing"
        }
        
        # Save to DB immediately
        try:
            verdicts_col.upsert(
                ids=[verdict_hash],
                documents=[json.dumps({
                    **result,
                    "claim": claim,
                    "timestamp": ts,
                    "claim_key": claim_key
                })],
                metadatas=[{
                    "claim_key": claim_key,
                    "timestamp": ts,
                    "status": "processing"
                }],
            )
        except Exception as e:
            logger.error(f"[DB] Failed to save verdict: {e}")
        
        # Add vote counts
        votes = votes_col.get(where={"ipfs_hash": verdict_hash})
        payload["human_upvotes"] = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
        payload["human_downvotes"] = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
        
        # Set web_url
        payload["web_url"] = f"{WEB_URL}/#/v/{verdict_hash}"
        
        # Store result for followers
        async with _inflight_lock:
            if claim_key in _inflight_requests:
                event, _ = _inflight_requests[claim_key]
                _inflight_requests[claim_key] = (event, payload)
                event.set()  # Wake up all waiting requests
        
        # Clean up after 60 seconds
        async def cleanup():
            await asyncio.sleep(60)
            async with _inflight_lock:
                if claim_key in _inflight_requests:
                    del _inflight_requests[claim_key]
                    logger.info(f"[COALESCE] Cleaned up: {claim_key}")
        
        asyncio.create_task(cleanup())
        
        # Log activity
        _activity_log.append({
            "type": "verify",
            "claim": claim,
            "verdict": verdict_key,
            "ts": ts
        })
        
        total_time = time.time() - start_time
        logger.info(f"[VERIFY] COMPLETE: {total_time:.2f}s total (pipeline: {pipeline_time:.2f}s)")
        
        # 🔥 FIX #1: IPFS upload in background
        asyncio.create_task(upload_to_ipfs_async(verdict_hash, result, claim))
        
        # Broadcast to SSE clients
        await broadcast({"type": "new_verdict", "data": payload})
        
        # Discord webhook (also async)
        asyncio.create_task(post_to_discord_webhook(payload))
        
        return payload
        
    except Exception as e:
        logger.error(f"[VERIFY] Pipeline failed: {e}")
        # Wake up followers with error
        async with _inflight_lock:
            if claim_key in _inflight_requests:
                event, _ = _inflight_requests[claim_key]
                event.set()
                del _inflight_requests[claim_key]
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")



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


@app.get("/stats")
def get_platform_stats():
    """Get platform-wide statistics."""
    try:
        # Count total verdicts
        verdicts = verdicts_col.get(limit=10000)
        total_verdicts = len(verdicts["ids"])
        
        # Count total votes
        votes = votes_col.get(limit=10000)
        total_votes = len(votes["ids"])
        
        # Count total API keys
        api_keys = api_key_manager.keys_col.get(limit=10000)
        total_keys = len(api_keys["ids"])
        
        return {
            "total_verdicts": total_verdicts,
            "total_votes": total_votes,
            "total_api_keys": total_keys,
            "timestamp": datetime.now(tz=timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"[STATS] Failed: {e}")
        return {
            "total_verdicts": 0,
            "total_votes": 0,
            "total_api_keys": 0
        }


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Test ChromaDB
        verdicts_col.get(limit=1)
        return {
            "status": "healthy",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "components": {
                "api": "ok",
                "database": "ok",
                "sse_clients": len(_sse_clients)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unhealthy: {str(e)}")


# ── API Key Management ────────────────────────────────────────────────────────
@app.post("/api-keys/generate")
async def generate_api_key(body: APIKeyRequest):
    """Generate a new API key.
    
    Free tier: 100 requests/day
    
    Request body:
    {
      "name": "Your Name or Organization",
      "email": "your@email.com",
      "use_case": "Optional: describe your use case"
    }
    """
    # Validate inputs
    if not body.name or len(body.name) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters")
    
    if not body.email or "@" not in body.email:
        raise HTTPException(status_code=400, detail="Valid email required")
    
    # Generate key
    try:
        api_key = api_key_manager.generate_key(
            name=body.name,
            email=body.email,
            tier="free"
        )
        
        logger.info(f"[API_KEY] Generated for {body.name} ({body.email})")
        
        return {
            "api_key": api_key,
            "tier": "free",
            "daily_limit": 100,
            "message": "Save this key securely. It will not be shown again.",
            "usage": f"Add header: Authorization: Bearer {api_key}"
        }
    except Exception as e:
        logger.error(f"[API_KEY] Generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate API key")


@app.get("/api-keys/usage")
async def get_api_key_usage(authorization: str = Header(default="")):
    """Get usage statistics for your API key.
    
    Requires: Authorization header with your API key
    """
    api_key = get_api_key(authorization)
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required in Authorization header")
    
    usage = api_key_manager.get_usage(api_key)
    if not usage:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return usage


# ── Badge Generation ──────────────────────────────────────────────────────────
@app.get("/badge/{ipfs_hash}.svg")
async def get_badge_svg(ipfs_hash: str):
    """Generate SVG badge for a verified claim."""
    from fastapi.responses import Response
    
    # Fetch verdict
    results = verdicts_col.get(ids=[ipfs_hash])
    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Verdict not found")
    
    data = json.loads(results["documents"][0])
    
    # Extract verdict and claim
    published = data.get("published", "")
    verdict_line = next((l for l in published.splitlines() if "VERDICT" in l.upper()), "")
    verdict_key = next((k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED")
    claim = data.get("claim") or data.get("content", "Unknown claim")
    
    # Generate SVG
    svg = generate_badge_svg(verdict_key, claim)
    
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
            "Content-Disposition": f'inline; filename="crawlconda-{ipfs_hash[:8]}.svg"'
        }
    )


@app.get("/badge/{ipfs_hash}/embed")
async def get_badge_embed(ipfs_hash: str):
    """Get HTML/Markdown embed codes for a badge."""
    # Fetch verdict
    results = verdicts_col.get(ids=[ipfs_hash])
    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Verdict not found")
    
    data = json.loads(results["documents"][0])
    
    # Extract verdict and claim
    published = data.get("published", "")
    verdict_line = next((l for l in published.splitlines() if "VERDICT" in l.upper()), "")
    verdict_key = next((k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED")
    claim = data.get("claim") or data.get("content", "Unknown claim")
    
    # Generate embed codes
    html = generate_badge_html(ipfs_hash, verdict_key, claim, WEB_URL)
    markdown = generate_badge_markdown(ipfs_hash, verdict_key, WEB_URL)
    
    return {
        "ipfs_hash": ipfs_hash,
        "verdict": verdict_key,
        "claim": claim,
        "badge_url": f"{WEB_URL}/badge/{ipfs_hash}.svg",
        "embed": {
            "html": html,
            "markdown": markdown,
            "url": f"{WEB_URL}/#/v/{ipfs_hash}"
        }
    }


# ── Claim Page with OG Tags ──────────────────────────────────────────────────
@app.get("/claim/{ipfs_hash}")
async def get_claim_page(ipfs_hash: str):
    """Serve HTML page with Open Graph meta tags for social sharing."""
    from fastapi.responses import HTMLResponse
    import html as html_escape
    
    # Fetch verdict
    results = verdicts_col.get(ids=[ipfs_hash])
    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Verdict not found")
    
    data = json.loads(results["documents"][0])
    
    # Extract data
    published = data.get("published", "")
    verdict_line = next((l for l in published.splitlines() if "VERDICT" in l.upper()), "")
    verdict_key = next((k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED")
    claim_raw = data.get("claim") or data.get("content", "Unknown claim")
    summary_raw = published.replace(verdict_line, "").strip()[:200]
    
    # Escape for HTML
    claim = html_escape.escape(claim_raw)
    summary = html_escape.escape(summary_raw)
    verdict_escaped = html_escape.escape(verdict_key)
    
    # Get vote counts
    votes = votes_col.get(where={"ipfs_hash": ipfs_hash})
    up = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
    down = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
    
    # Verdict emoji for visual appeal
    emoji_map = {
        "CONFIRMED": "✅",
        "PARTIALLY CONFIRMED": "🟡",
        "UNCONFIRMED": "⚠️",
        "FALSE": "❌"
    }
    emoji = emoji_map.get(verdict_key, "🔍")
    
    # Color scheme
    color_map = {
        "CONFIRMED": "#22c55e",
        "PARTIALLY CONFIRMED": "#eab308",
        "UNCONFIRMED": "#f97316",
        "FALSE": "#ef4444"
    }
    color = color_map.get(verdict_key, "#888888")
    
    # OG Image: Use a data URI with inline SVG for better compatibility
    og_image_url = f"{WEB_URL}/og-image/{ipfs_hash}.png"
    
    # Generate HTML with proper OG tags
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  
  <!-- Primary Meta Tags -->
  <title>{emoji} {verdict_escaped}: {claim[:60]}</title>
  <meta name="title" content="{emoji} {verdict_escaped}: {claim[:60]}">
  <meta name="description" content="{summary}">
  <meta name="author" content="CrawlConda">
  
  <!-- Open Graph / Facebook -->
  <meta property="og:type" content="article">
  <meta property="og:url" content="{WEB_URL}/claim/{ipfs_hash}">
  <meta property="og:title" content="{emoji} {verdict_escaped}">
  <meta property="og:description" content="{claim[:150]}">
  <meta property="og:image" content="{og_image_url}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:site_name" content="CrawlConda · Ground Truth Engine">
  
  <!-- Twitter -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="{WEB_URL}/claim/{ipfs_hash}">
  <meta name="twitter:title" content="{emoji} {verdict_escaped}">
  <meta name="twitter:description" content="{claim[:150]}">
  <meta name="twitter:image" content="{og_image_url}">
  <meta name="twitter:site" content="@CrawlConda">
  
  <!-- LinkedIn -->
  <meta property="og:image:alt" content="CrawlConda Verification: {verdict_escaped}">
  
  <!-- Redirect to main app after 1 second -->
  <meta http-equiv="refresh" content="1; url={WEB_URL}/#/v/{ipfs_hash}">
  
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: linear-gradient(135deg, #0d0d0d 0%, #1a1a1a 100%);
      color: #e8e8e8;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }}
    .container {{
      max-width: 600px;
      background: #141414;
      border: 2px solid {color};
      border-radius: 16px;
      padding: 40px;
      text-align: center;
      box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    }}
    .emoji {{
      font-size: 4rem;
      margin-bottom: 20px;
      display: block;
    }}
    .verdict {{
      font-size: 1.8rem;
      font-weight: 800;
      color: {color};
      margin-bottom: 20px;
      letter-spacing: 1px;
    }}
    .claim {{
      font-size: 1.1rem;
      line-height: 1.6;
      color: #ccc;
      margin-bottom: 24px;
      padding: 20px;
      background: #0a0a0a;
      border-radius: 8px;
      border-left: 4px solid {color};
    }}
    .summary {{
      font-size: 0.95rem;
      color: #888;
      line-height: 1.6;
      margin-bottom: 24px;
    }}
    .votes {{
      font-size: 0.9rem;
      color: #666;
      margin-bottom: 24px;
    }}
    .votes span {{
      margin: 0 8px;
      font-weight: 600;
    }}
    .votes .up {{ color: #22c55e; }}
    .votes .down {{ color: #ef4444; }}
    .cta {{
      display: inline-block;
      background: {color};
      color: #fff;
      padding: 14px 32px;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 600;
      font-size: 1rem;
      transition: transform 0.2s, box-shadow 0.2s;
    }}
    .cta:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 20px rgba(124, 106, 247, 0.3);
    }}
    .footer {{
      margin-top: 32px;
      font-size: 0.8rem;
      color: #444;
    }}
    .loader {{
      margin-top: 20px;
      font-size: 0.85rem;
      color: #666;
    }}
  </style>
</head>
<body>
  <div class="container">
    <span class="emoji">{emoji}</span>
    <div class="verdict">{verdict_escaped}</div>
    <div class="claim">{claim}</div>
    <div class="summary">{summary}</div>
    <div class="votes">
      <span class="up">↑ {up}</span>
      <span class="down">↓ {down}</span>
    </div>
    <a href="{WEB_URL}/#/v/{ipfs_hash}" class="cta">View Full Verification</a>
    <div class="footer">CrawlConda · Ground Truth Engine</div>
    <div class="loader">Redirecting...</div>
  </div>
</body>
</html>'''
    
    return HTMLResponse(content=html_content)


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Test ChromaDB
        verdicts_col.get(limit=1)
        return {
            "status": "healthy",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "components": {
                "api": "ok",
                "database": "ok",
                "sse_clients": len(_sse_clients)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unhealthy: {str(e)}")


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

    return {"recovered": recovered, "skipped": skipped, "total_pins": len(pins)}# Add this to api.py after the get_badge_svg endpoint

@app.get("/og-image/{ipfs_hash}.png")
async def get_og_image(ipfs_hash: str):
    """Generate Open Graph image (1200x630) for social media sharing."""
    from fastapi.responses import Response
    import html as html_escape
    
    # Fetch verdict
    results = verdicts_col.get(ids=[ipfs_hash])
    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Verdict not found")
    
    data = json.loads(results["documents"][0])
    
    # Extract data
    published = data.get("published", "")
    verdict_line = next((l for l in published.splitlines() if "VERDICT" in l.upper()), "")
    verdict_key = next((k for k in VERDICT_ORDER if k in verdict_line.upper()), "UNCONFIRMED")
    claim_raw = data.get("claim") or data.get("content", "Unknown claim")
    
    # Truncate claim for image
    claim = claim_raw[:120] + ("..." if len(claim_raw) > 120 else "")
    claim_escaped = html_escape.escape(claim)
    verdict_escaped = html_escape.escape(verdict_key)
    
    # Color scheme
    color_map = {
        "CONFIRMED": "#22c55e",
        "PARTIALLY CONFIRMED": "#eab308",
        "UNCONFIRMED": "#f97316",
        "FALSE": "#ef4444"
    }
    color = color_map.get(verdict_key, "#888888")
    
    # Generate SVG (social platforms will render as PNG)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#0d0d0d;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#1a1a1a;stop-opacity:1" />
    </linearGradient>
  </defs>
  
  <!-- Background -->
  <rect width="1200" height="630" fill="url(#bg)"/>
  
  <!-- Border -->
  <rect x="40" y="40" width="1120" height="550" rx="16" fill="none" stroke="{color}" stroke-width="4"/>
  
  <!-- Logo -->
  <text x="100" y="120" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" 
        font-size="32" font-weight="700" fill="#7c6af7">CrawlConda</text>
  <text x="100" y="155" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" 
        font-size="18" font-weight="400" fill="#666">Ground Truth Engine</text>
  
  <!-- Verdict Badge -->
  <rect x="100" y="200" width="300" height="60" rx="30" fill="{color}"/>
  <text x="250" y="240" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" 
        font-size="28" font-weight="800" fill="#ffffff" text-anchor="middle">{verdict_escaped}</text>
  
  <!-- Claim Text (wrapped) -->
  <foreignObject x="100" y="290" width="1000" height="200">
    <div xmlns="http://www.w3.org/1999/xhtml" style="
      font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif;
      font-size: 32px;
      line-height: 1.4;
      color: #e8e8e8;
      font-weight: 500;
    ">{claim_escaped}</div>
  </foreignObject>
  
  <!-- Footer -->
  <text x="100" y="550" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" 
        font-size="16" fill="#666">Verified by CrawlConda · Source-grounded fact-checking</text>
</svg>'''
    
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
            "Content-Disposition": f'inline; filename="og-{ipfs_hash[:8]}.svg"'
        }
    )
