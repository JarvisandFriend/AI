#!/bin/bash
set -e

# Installs `finch` as a global command that runs agent.py regardless of
# which directory you're standing in when you call it.

INSTALL_DIR="$HOME/.finch"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

cp agent.py "$INSTALL_DIR/agent.py"
cp tools.py "$INSTALL_DIR/tools.py"
cp requirements.txt "$INSTALL_DIR/requirements.txt"

echo "Installing dependencies..."
pip install -r "$INSTALL_DIR/requirements.txt" --break-system-packages

cat > "$BIN_DIR/finch" << EOF
#!/bin/bash
exec python3 "$INSTALL_DIR/agent.py" "\$@"
EOF

chmod +x "$BIN_DIR/finch"

if ! echo "$PATH" | grep -q "$BIN_DIR"; then
    echo "export PATH=\"$BIN_DIR:\$PATH\"" >> ~/.bashrc
    echo "Added $BIN_DIR to PATH in ~/.bashrc — run 'source ~/.bashrc' or open a new shell."
fi

echo "Installed. Usage:"
echo "  finch                  # run in current directory"
echo "  finch --no-thinking    # skip reasoning phase"
echo "  finch --dir some/path  # run against a specific directory"
