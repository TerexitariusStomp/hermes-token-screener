#!/bin/bash
# Bonsai-8B llama-server for Hermes
# Starts PrismML llama-server on port 8083

MODEL="/home/terexitarius/.hermes/models/Bonsai-8B.gguf"
PORT=8083
LOG="$HOME/.hermes/logs/bonsai-server.log"
LLAMA_BIN="$HOME/prism-llama.cpp/build/bin/llama-server"

mkdir -p "$(dirname "$LOG")"

# Check if already running
if curl -s -o /dev/null -w '' http://127.0.0.1:$PORT/health 2>/dev/null; then
    echo "Bonsai server already running on port $PORT"
    exit 0
fi

echo "Starting Bonsai-8B server on port $PORT..."
nohup "$LLAMA_BIN" \
    -m "$MODEL" \
    -ngl 99 \
    -c 65536 \
    -b 512 \
    --host 127.0.0.1 \
    --port $PORT \
    >> "$LOG" 2>&1 &

echo "PID: $!"

# Wait for ready
for i in $(seq 1 30); do
    sleep 1
    if curl -s -o /dev/null -w '' http://127.0.0.1:$PORT/health 2>/dev/null; then
        echo "Ready after ${i}s"
        exit 0
    fi
done

echo "Warning: Server may still be loading. Check $LOG"
