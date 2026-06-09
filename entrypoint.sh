#!/bin/bash
set -e

echo "[entrypoint] Starting PLUR RFP Tracker"
ls /
ls $SSL_KEY_PATH
cert_args=""
if [ -f $SSL_KEY_PATH ]; then
   cert_args="--ssl-keyfile=$SSL_KEY_PATH --ssl-certfile=$SSL_CERT_PATH"
else
    echo "$SSL_KEY_PATH not found"
fi

# Start the dashboard in background
uvicorn web.app:app --host 0.0.0.0 --port 8081 $cert_args &
UVICORN_PID=$!
echo "[entrypoint] Dashboard started (PID $UVICORN_PID)"

# Wait for uvicorn to be ready before scraping
sleep 10

# Run scrapers once at startup
echo "[entrypoint] Running initial scrape..."
python run.py --once || echo "[entrypoint] Initial scrape had errors (non-fatal)"

# Loop: run scrapers every 24 hours
while true; do
    sleep 86400
    echo "[entrypoint] Running scheduled scrape..."
    python run.py --once || echo "[entrypoint] Scheduled scrape had errors (non-fatal)"
done &

# Wait on uvicorn - if it dies, container exits
wait $UVICORN_PID
