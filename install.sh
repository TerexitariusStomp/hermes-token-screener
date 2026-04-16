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
pip install -e ".[all]" > /dev/null 2>&1
echo -e "  ${GREEN}✓${NC} Python packages installed"

# Step 5: Create directories
echo "[5/7] Creating directories..."
mkdir -p ~/.hermes/data/token_screener
mkdir -p ~/.hermes/logs
mkdir -p ~/.hermes/scripts
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
python3 -c "
import sqlite3
from hermes_screener.utils import ensure_tables
import os

db_path = os.path.expanduser('~/.hermes/data/central_contracts.db')
conn = sqlite3.connect(db_path)
ensure_tables(conn)
conn.close()
print('  ✓ Contracts database initialized')
" 2>/dev/null || echo -e "  ${YELLOW}!${NC} Database initialization skipped (will auto-create on first run)"

echo ""
echo "============================================"
echo "  Installation Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit ~/.hermes/.env and add your API keys"
echo ""
echo "  2. Test the pipeline:"
echo "     python3 scripts/discovery/telegram_scraper.py --dry-run"
echo "     python3 scripts/discovery/token_discovery.py"
echo "     python3 scripts/enrichment/token_enricher.py --max-tokens 10"
echo ""
echo "  3. Set up cron jobs (see README.md)"
echo ""
echo "  4. Start the dashboard:"
echo "     python3 -m hermes_screener.cli dashboard"
echo ""
