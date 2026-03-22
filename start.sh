#!/bin/bash
# CLEANED: Requires bash 4.3+ for 'wait -n' (Railway uses Ubuntu 22.04 / bash 5.1)
set -e

echo "[START] CrawlConda unified service starting..."
echo "[START] Both processes share ./crawlconda_data/ (ChromaDB)"

# Start FastAPI in background
uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} &
API_PID=$!
echo "[START] API started (PID $API_PID) on port ${PORT:-8000}"

# Brief pause for API to initialize before bot imports it
sleep 3

# Start Discord bot in background
python crawlconda_swarm.py &
BOT_PID=$!
echo "[START] Discord bot started (PID $BOT_PID)"

echo "[START] Both processes running. Monitoring..."

# Exit if either process dies — Railway will restart the service
wait -n
echo "[START] A process exited. Shutting down..."
kill $API_PID $BOT_PID 2>/dev/null
exit 1
