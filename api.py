from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
import chromadb
import json

from crawlconda_swarm import run_swarm, VERDICT_EMOJI

app = FastAPI(title="CrawlConda API")

chroma = chromadb.PersistentClient(path="./crawlconda_data")
verdicts_col = chroma.get_or_create_collection("verified_crawlconda")
votes_col = chroma.get_or_create_collection("human_votes")


class VoteRequest(BaseModel):
    vote: str          # "up" or "down"
    user_id: str


@app.get("/verify")
async def verify(claim: str):
    result = await run_swarm(claim)
    ipfs_hash = result["ipfs"].split("/")[-1]
    verdict_line = next((l for l in result["published"].splitlines() if "VERDICT" in l.upper()), "")
    verdict_key = next((k for k in VERDICT_EMOJI if k in verdict_line.upper()), "UNCONFIRMED")
    sources = [
        {"title": p[0], "url": p[1], "source": p[2]}
        for entry in result["sources"].split("|||")[:8]
        if len(p := entry.split("||")) >= 3
    ]
    return {
        "claim": claim,
        "verdict": verdict_key,
        "emoji": VERDICT_EMOJI[verdict_key],
        "summary": result["published"],
        "sources": sources,
        "ipfs_hash": ipfs_hash,
        "ipfs_url": result["ipfs"],
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@app.post("/confirm/{ipfs_hash}")
def confirm(ipfs_hash: str, body: VoteRequest):
    if body.vote not in ("up", "down"):
        raise HTTPException(status_code=400, detail="vote must be 'up' or 'down'")
    vote_id = f"{ipfs_hash}:{body.user_id}"
    existing = votes_col.get(ids=[vote_id])
    if existing["ids"]:
        votes_col.update(ids=[vote_id], documents=[body.vote], metadatas=[{"ipfs_hash": ipfs_hash, "user_id": body.user_id, "vote": body.vote}])
        return {"status": "updated", "vote": body.vote}
    votes_col.add(ids=[vote_id], documents=[body.vote], metadatas=[{"ipfs_hash": ipfs_hash, "user_id": body.user_id, "vote": body.vote}])
    return {"status": "recorded", "vote": body.vote}


@app.get("/verdict/{ipfs_hash}")
def get_verdict(ipfs_hash: str):
    results = verdicts_col.get(ids=[ipfs_hash])
    if not results["ids"]:
        raise HTTPException(status_code=404, detail="Verdict not found")
    data = json.loads(results["documents"][0])
    votes = votes_col.get(where={"ipfs_hash": ipfs_hash})
    up = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
    down = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
    return {**data, "ipfs_hash": ipfs_hash, "human_upvotes": up, "human_downvotes": down}


@app.get("/verdicts")
def list_verdicts(limit: int = 20):
    results = verdicts_col.get(limit=limit)
    out = []
    for doc_id, doc in zip(results["ids"], results["documents"]):
        try:
            data = json.loads(doc)
            ipfs_hash = data.get("ipfs", "").split("/")[-1]
            votes = votes_col.get(where={"ipfs_hash": ipfs_hash}) if ipfs_hash else {"metadatas": []}
            up = sum(1 for v in votes["metadatas"] if v["vote"] == "up")
            down = sum(1 for v in votes["metadatas"] if v["vote"] == "down")
            out.append({"id": doc_id, "ipfs_hash": ipfs_hash, "human_upvotes": up, "human_downvotes": down, **data})
        except Exception:
            continue
    return {"verdicts": out, "count": len(out)}


@app.post("/recover")
async def recover_from_pinata():
    """Rebuild local ChromaDB index from all pins on Pinata. Run this if crawlconda_data/ is lost."""
    import httpx, os
    pinata_jwt = os.getenv("PINATA_JWT")
    if not pinata_jwt:
        raise HTTPException(status_code=500, detail="PINATA_JWT not set")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.pinata.cloud/data/pinList?status=pinned&pageLimit=1000&metadata[name]=crawlconda",
            headers={"Authorization": f"Bearer {pinata_jwt}"},
            timeout=30,
        )
        resp.raise_for_status()
        pins = resp.json().get("rows", [])
    recovered, skipped = 0, 0
    for pin in pins:
        ipfs_hash = pin["ipfs_pin_hash"]
        existing = verdicts_col.get(ids=[ipfs_hash])
        if existing["ids"]:
            skipped += 1
            continue
        async with httpx.AsyncClient() as client:
            try:
                r = await client.get(f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}", timeout=15)
                data = r.json()
                verdicts_col.add(ids=[ipfs_hash], documents=[json.dumps(data)])
                recovered += 1
            except Exception:
                skipped += 1
    return {"recovered": recovered, "skipped": skipped, "total_pins": len(pins)}
