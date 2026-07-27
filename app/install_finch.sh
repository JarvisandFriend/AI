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
CHECK_LOG="$INSTALL_DIR/.install_check.log"
if ! python3 -c "
import requests
import rich
" 2>"$CHECK_LOG"; then
    echo ""
    echo "ERROR: dependencies did not install correctly."
    cat "$CHECK_LOG"
    exit 1
fi
rm -f "$CHECK_LOG"
echo "Dependencies installed and importable."

# --- key helper: writes/updates a single KEY=value line in ENV_FILE ---
set_env_key() {
    local key_name="$1"
    local value="$2"
    touch "$ENV_FILE"
    if grep -q "^${key_name}=" "$ENV_FILE" 2>/dev/null; then
        # replace existing line
        tmp="$(mktemp)"
        grep -v "^${key_name}=" "$ENV_FILE" > "$tmp" || true
        mv "$tmp" "$ENV_FILE"
    fi
    echo "${key_name}=${value}" >> "$ENV_FILE"
    chmod 600 "$ENV_FILE"
}

# --- Mistral key setup ---
# Priority: existing env var > existing saved key (skip prompt) > prompt now.
if [ -n "$MISTRAL_API_KEY" ]; then
    set_env_key "MISTRAL_API_KEY" "$MISTRAL_API_KEY"
    echo "Found MISTRAL_API_KEY in current environment — saved it for finch."
elif [ -f "$ENV_FILE" ] && grep -q "^MISTRAL_API_KEY=" "$ENV_FILE"; then
    echo "Existing Mistral API key found at $ENV_FILE — keeping it."
    echo "(Run 'finch --set model' to change it later.)"
else
    echo ""
    read -rp "Enter your Mistral API key (from console.mistral.ai): " ENTERED_KEY
    if [ -z "$ENTERED_KEY" ]; then
        echo "No key entered — skipping. You can set one later with 'finch --set model'"
        echo "or by exporting MISTRAL_API_KEY yourself before running finch."
    else
        set_env_key "MISTRAL_API_KEY" "$ENTERED_KEY"
        echo "Saved key to $ENV_FILE (permissions restricted to your user)."
    fi
fi

# --- Gemini key setup (powers the web_search tool) ---
if [ -n "$GEMINI_API_KEY" ]; then
    set_env_key "GEMINI_API_KEY" "$GEMINI_API_KEY"
    echo "Found GEMINI_API_KEY in current environment — saved it for finch."
elif [ -f "$ENV_FILE" ] && grep -q "^GEMINI_API_KEY=" "$ENV_FILE"; then
    echo "Existing Gemini API key found at $ENV_FILE — keeping it."
    echo "(Run 'finch --set search' to change it later.)"
else
    echo ""
    read -rp "Enter your Gemini API key (from aistudio.google.com/apikey), or leave blank to skip: " ENTERED_KEY
    if [ -z "$ENTERED_KEY" ]; then
        echo "No key entered — web_search tool will be unavailable until you run 'finch --set search'."
    else
        set_env_key "GEMINI_API_KEY" "$ENTERED_KEY"
        echo "Saved key to $ENV_FILE (permissions restricted to your user)."
    fi
fi

# --- finch launcher ---
cat > "$BIN_DIR/finch" << 'EOF'
#!/bin/bash
INSTALL_DIR="$HOME/.finch"
ENV_FILE="$INSTALL_DIR/env"

set_env_key() {
    local key_name="$1"
    local value="$2"
    touch "$ENV_FILE"
    if grep -q "^${key_name}=" "$ENV_FILE" 2>/dev/null; then
        tmp="$(mktemp)"
        grep -v "^${key_name}=" "$ENV_FILE" > "$tmp" || true
        mv "$tmp" "$ENV_FILE"
    fi
    echo "${key_name}=${value}" >> "$ENV_FILE"
    chmod 600 "$ENV_FILE"
}

unset_env_key() {
    local key_name="$1"
    if [ -f "$ENV_FILE" ] && grep -q "^${key_name}=" "$ENV_FILE"; then
        tmp="$(mktemp)"
        grep -v "^${key_name}=" "$ENV_FILE" > "$tmp" || true
        mv "$tmp" "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        echo "${key_name} removed."
    else
        echo "${key_name} was not set — nothing to remove."
    fi
}

case "$1" in
    --set)
        case "$2" in
            model)
                read -rp "Enter your Mistral API key (from console.mistral.ai): " ENTERED_KEY
                if [ -n "$ENTERED_KEY" ]; then
                    set_env_key "MISTRAL_API_KEY" "$ENTERED_KEY"
                    echo "MISTRAL_API_KEY updated."
                else
                    echo "No key entered — nothing changed."
                fi
                ;;
            search)
                read -rp "Enter your Gemini API key (from aistudio.google.com/apikey): " ENTERED_KEY
                if [ -n "$ENTERED_KEY" ]; then
                    set_env_key "GEMINI_API_KEY" "$ENTERED_KEY"
                    echo "GEMINI_API_KEY updated."
                else
                    echo "No key entered — nothing changed."
                fi
                ;;
            *)
                echo "Usage: finch --set model|search"
                ;;
        esac
        exit 0
        ;;
    --unset)
        case "$2" in
            model)
                unset_env_key "MISTRAL_API_KEY"
                ;;
            search)
                unset_env_key "GEMINI_API_KEY"
                ;;
            *)
                echo "Usage: finch --unset model|search"
                ;;
        esac
        exit 0
        ;;
esac

# Load saved keys if not already present in this shell's environment.
if [ -f "$ENV_FILE" ]; then
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
echo "  finch --set model      # set/update your Mistral API key"
echo "  finch --set search     # set/update your Gemini API key (web_search tool)"
echo "  finch --unset model    # remove the saved Mistral API key"
echo "  finch --unset search   # remove the saved Gemini API key"
