#!/bin/bash
set -e

echo "[START] CrawlConda unified service starting..."
echo "[START] Both processes share ./crawlconda_data/ (ChromaDB)"

# Railway provides PORT env var, default to 8080 if not set
PORT=${PORT:-8080}
echo "[START] Using PORT: $PORT"

# Start FastAPI in background
uvicorn api:app --host 0.0.0.0 --port $PORT &
API_PID=$!
echo "[START] API started (PID $API_PID) on port $PORT"

# Brief pause for API to initialize
sleep 3

# Start Discord bot in background
python crawlconda_swarm.py &
BOT_PID=$!
echo "[START] Discord bot started (PID $BOT_PID)"

echo "[START] Both processes running. Monitoring..."

# Exit if either process dies
wait -n
echo "[START] A process exited. Shutting down..."
kill $API_PID $BOT_PID 2>/dev/null
exit 1
