#!/bin/bash
set -e
# Installs `finch` as a global command that runs agent.py regardless of
# which directory you're standing in when you call it.
INSTALL_DIR="$HOME/.finch"
BIN_DIR="$HOME/.local/bin"
ENV_FILE="$INSTALL_DIR/env"

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

cp agent.py "$INSTALL_DIR/agent.py"
cp tools.py "$INSTALL_DIR/tools.py"
cp requirements.txt "$INSTALL_DIR/requirements.txt"

echo "Installing dependencies..."
pip install -r "$INSTALL_DIR/requirements.txt" --break-system-packages \
    --force-reinstall --no-cache-dir

echo "Verifying installation..."
if ! python3 -c "
import requests
import rich
" 2>/tmp/finch_install_check.log; then
    echo ""
    echo "ERROR: dependencies did not install correctly."
    cat /tmp/finch_install_check.log
    exit 1
fi
rm -f /tmp/finch_install_check.log
echo "Dependencies installed and importable."

# --- API key setup ---
# Priority: existing env var > existing saved key (skip prompt) > prompt now.
if [ -n "$MISTRAL_API_KEY" ]; then
    echo "MISTRAL_API_KEY=$MISTRAL_API_KEY" > "$ENV_FILE"
    echo "Found MISTRAL_API_KEY in current environment — saved it for finch."
elif [ -f "$ENV_FILE" ] && grep -q "^MISTRAL_API_KEY=" "$ENV_FILE"; then
    echo "Existing Mistral API key found at $ENV_FILE — keeping it."
    echo "(Run 'finch --set-key' to change it later.)"
else
    echo ""
    read -rsp "Enter your Mistral API key (from console.mistral.ai): " ENTERED_KEY
    echo ""
    if [ -z "$ENTERED_KEY" ]; then
        echo "No key entered — skipping. You can set one later with 'finch --set-key'"
        echo "or by exporting MISTRAL_API_KEY yourself before running finch."
    else
        echo "MISTRAL_API_KEY=$ENTERED_KEY" > "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        echo "Saved key to $ENV_FILE (permissions restricted to your user)."
    fi
fi

# --- finch launcher ---
cat > "$BIN_DIR/finch" << 'EOF'
#!/bin/bash
INSTALL_DIR="$HOME/.finch"
ENV_FILE="$INSTALL_DIR/env"

if [ "$1" = "--set-key" ]; then
    read -rsp "Enter your Mistral API key (from console.mistral.ai): " ENTERED_KEY
    echo ""
    if [ -n "$ENTERED_KEY" ]; then
        echo "MISTRAL_API_KEY=$ENTERED_KEY" > "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        echo "Key updated."
    else
        echo "No key entered — nothing changed."
    fi
    exit 0
fi

# Load saved key if not already present in this shell's environment.
if [ -z "$MISTRAL_API_KEY" ] && [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

exec python3 "$INSTALL_DIR/agent.py" "$@"
EOF
chmod +x "$BIN_DIR/finch"

if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    echo "export PATH=\"$BIN_DIR:\$PATH\"" >> ~/.bashrc
    echo "Added $BIN_DIR to PATH in ~/.bashrc — run 'source ~/.bashrc' or open a new shell."
fi

echo "Installed. Usage:"
echo "  finch                  # run in current directory"
echo "  finch --model <name>   # use a specific Mistral model"
echo "  finch --dir some/path  # run against a specific directory"
echo "  finch --set-key        # update your saved Mistral API key"
