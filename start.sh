#!/bin/bash
set -e

echo "Starting CrawlConda unified service..."

# Start the API in the background
uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000} &
API_PID=$!

# Give API 3 seconds to initialize
sleep 3

# Start the Discord bot in the background
python crawlconda_swarm.py &
BOT_PID=$!

echo "API PID: $API_PID | Bot PID: $BOT_PID"

# If either process dies, kill the other and exit
wait -n
kill $API_PID $BOT_PID 2>/dev/null
exit 1
