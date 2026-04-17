#!/bin/bash
set -e

echo "============================================"
echo "  Hermes Token Screener - Installer"
echo "============================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Step 1: Check prerequisites
echo "[1/7] Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERROR: Python 3.10+ is required${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo -e "  ${GREEN}✓${NC} Python $PYTHON_VERSION"
else
    echo -e "  ${RED}✗${NC} Python 3.10+ required (found $PYTHON_VERSION)"
    exit 1
fi

# Step 2: Install Node.js (for GMGN CLI)
echo "[2/7] Checking Node.js..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    echo -e "  ${GREEN}✓${NC} Node.js $NODE_VERSION"
else
    echo -e "  ${YELLOW}!${NC} Node.js not found. Installing..."
    if command -v apt-get &> /dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash - > /dev/null 2>&1
        sudo apt-get install -y nodejs > /dev/null 2>&1
        echo -e "  ${GREEN}✓${NC} Node.js installed"
    else
        echo -e "  ${YELLOW}!${NC} Please install Node.js 22+ manually: https://nodejs.org"
    fi
fi

# Step 3: Install Surf CLI
echo "[3/7] Checking Surf CLI..."
if command -v surf &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} Surf CLI installed"
else
    echo -e "  ${YELLOW}!${NC} Installing Surf CLI..."
    curl -sSf https://agent.asksurf.ai/cli/releases/install.sh | bash > /dev/null 2>&1 || true
    echo -e "  ${GREEN}✓${NC} Surf CLI installed"
fi

# Step 4: Install Python dependencies
echo "[4/7] Installing Python dependencies..."
PIP_LOG=$(mktemp /tmp/hermes-install-pip.XXXXXX.log)
if ! python3 -m pip install -e ".[all]" > "$PIP_LOG" 2>&1; then
    if grep -q "externally-managed-environment" "$PIP_LOG"; then
        echo -e "  ${YELLOW}!${NC} PEP 668 environment detected, retrying with --break-system-packages..."
        if ! python3 -m pip install --break-system-packages --ignore-installed -e ".[all]" > "$PIP_LOG" 2>&1; then
            echo -e "  ${RED}✗${NC} Python dependency installation failed"
            tail -40 "$PIP_LOG"
            exit 1
        fi
    else
        echo -e "  ${RED}✗${NC} Python dependency installation failed"
        tail -40 "$PIP_LOG"
        exit 1
    fi
fi
echo -e "  ${GREEN}✓${NC} Python packages installed"

# Step 5: Create directories
echo "[5/7] Creating directories..."
mkdir -p ~/.hermes/data
mkdir -p ~/.hermes/data/token_screener
mkdir -p ~/.hermes/logs
mkdir -p ~/.hermes/scripts
mkdir -p ~/.hermes/.telegram_session
echo -e "  ${GREEN}✓${NC} Directories created at ~/.hermes/"

# Step 6: Set up environment file
echo "[6/7] Setting up environment..."
if [ ! -f ~/.hermes/.env ]; then
    cp .env.example ~/.hermes/.env
    echo -e "  ${GREEN}✓${NC} Created ~/.hermes/.env from template"
    echo -e "  ${YELLOW}!${NC} Edit ~/.hermes/.env and add your API keys"
else
    echo -e "  ${GREEN}✓${NC} ~/.hermes/.env already exists"
fi

# Step 7: Initialize databases
echo "[7/7] Initializing databases..."
if python3 - <<'PY'
import os
import sqlite3

DB_PATH = os.path.expanduser('~/.hermes/data/central_contracts.db')
conn = sqlite3.connect(DB_PATH)
conn.executescript('''
CREATE TABLE IF NOT EXISTS telegram_contract_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    chain TEXT,
    contract_address TEXT NOT NULL,
    raw_address TEXT,
    address_source TEXT,
    message_text TEXT,
    observed_at REAL,
    session_source TEXT,
    inserted_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_calls_msg_contract
    ON telegram_contract_calls(message_id, contract_address);

CREATE TABLE IF NOT EXISTS telegram_contracts_unique (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain TEXT NOT NULL,
    contract_address TEXT NOT NULL,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    mentions INTEGER NOT NULL,
    last_channel_id TEXT,
    last_message_id INTEGER,
    last_raw_address TEXT,
    last_source TEXT,
    last_message_text TEXT,
    channel_count INTEGER NOT NULL DEFAULT 0,
    channels_seen TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_chain_addr
    ON telegram_contracts_unique(chain, contract_address);
''')
conn.commit()
conn.close()
print('  ✓ Contracts database initialized')
PY
then
    :
else
    echo -e "  ${YELLOW}!${NC} Database initialization skipped (will auto-create on first run)"
fi

echo ""
echo "============================================"
echo "  Installation Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit ~/.hermes/.env and add your API keys"
echo ""
echo "  2. Test the pipeline:"
echo "     python3 scripts/telegram_scraper.py --dry-run --max-dialogs 5"
echo "     python3 scripts/token_discovery.py"
echo "     python3 scripts/token_enricher.py --max-tokens 10"
echo ""
echo "  3. Set up cron jobs (see README.md)"
echo ""
echo "  4. Start the dashboard:"
echo "     uvicorn hermes_screener.dashboard.app:app --host 0.0.0.0 --port 8080"
echo ""
