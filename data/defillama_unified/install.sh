#!/bin/bash
# Install defillama-cli to /usr/local/bin
set -e

CLI_DIR="$HOME/.hermes/data/defillama_unified"
CLI_SCRIPT="$CLI_DIR/defillama-cli.py"
INSTALL_PATH="/usr/local/bin/defillama-cli"

echo "Installing defillama-cli..."

# Make script executable
chmod +x "$CLI_SCRIPT"

# Create symlink
if [ -L "$INSTALL_PATH" ]; then
    rm "$INSTALL_PATH"
fi
ln -sf "$CLI_SCRIPT" "$INSTALL_PATH"

echo "Installed: $INSTALL_PATH -> $CLI_SCRIPT"
echo ""
echo "Usage:"
echo "  defillama-cli chains --top 20"
echo "  defillama-cli chain base --rpcs --dexs --assets"
echo "  defillama-cli protocols --chain ethereum --top 10"
echo "  defillama-cli search uniswap"
echo "  defillama-cli stats"
echo ""
echo "Run 'defillama-cli --help' for all commands"
