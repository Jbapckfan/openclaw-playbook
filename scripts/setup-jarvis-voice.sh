#!/usr/bin/env bash
# setup-jarvis-voice.sh — Install additional dependencies for Jarvis conversational mode
# Adds: pynput (global hotkey listener)
# Creates: data dirs, launchd plist for jarvis-voice daemon
# Prerequisite: setup-voice-hub.sh must have been run first

set -euo pipefail

echo "╔══════════════════════════════════════╗"
echo "║  Jarvis Conversational Voice Setup   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# --- Preflight ---
VENV_DIR="${HOME}/jarvis/venvs/voice-hub"

if [[ ! -d "$VENV_DIR" ]]; then
    echo "ERROR: Voice Hub venv not found at ${VENV_DIR}"
    echo "       Run scripts/setup-voice-hub.sh first."
    exit 1
fi

source "${VENV_DIR}/bin/activate"
echo "Using venv: ${VENV_DIR}"

# --- Install pynput ---
echo ""
echo "=== Installing pynput (global hotkey listener) ==="
pip install pynput
echo "  ✓ pynput installed"

# --- Verify ---
echo ""
echo "=== Verifying pynput ==="
if python3 -c "from pynput import keyboard; print('pynput OK')" 2>/dev/null; then
    echo "  ✓ pynput imports correctly"
else
    echo "  ✗ pynput import failed"
    echo "    You may need to grant Accessibility permission to your terminal app."
    echo "    System Preferences → Privacy & Security → Accessibility → Enable your terminal"
fi

# --- Create data directories ---
echo ""
echo "=== Creating data directories ==="

mkdir -p "${HOME}/jarvis/data/voice"
mkdir -p "${HOME}/jarvis/logs"

echo "  ✓ ~/jarvis/data/voice/"
echo "  ✓ ~/jarvis/logs/"

# --- Create launchd plist ---
echo ""
echo "=== Creating launchd service ==="

PLIST_PATH="${HOME}/Library/LaunchAgents/com.openclaw.jarvis-voice.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.jarvis-voice</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/python3</string>
        <string>${SCRIPT_DIR}/jarvis-voice.py</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/jarvis/logs/jarvis-voice.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/jarvis/logs/jarvis-voice-error.log</string>
    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${VENV_DIR}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST

echo "  ✓ Launchd plist created: ${PLIST_PATH}"

# --- macOS Accessibility reminder ---
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  IMPORTANT: macOS Accessibility Permission Required     ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  pynput needs Accessibility access for global hotkeys.  ║"
echo "║                                                         ║"
echo "║  Go to: System Settings → Privacy & Security            ║"
echo "║         → Accessibility                                 ║"
echo "║  Enable your terminal app (Terminal, iTerm2, etc.)      ║"
echo "╚══════════════════════════════════════════════════════════╝"

# --- Summary ---
echo ""
echo "╔══════════════════════════════════════╗"
echo "║    Setup Complete!                   ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "To run Jarvis manually:"
echo "  source ${VENV_DIR}/bin/activate"
echo "  python3 ${SCRIPT_DIR}/jarvis-voice.py"
echo ""
echo "To test the pipeline (no mic needed):"
echo "  python3 ${SCRIPT_DIR}/jarvis-voice.py --test-pipeline \"Tell me a joke\""
echo ""
echo "To test the hotkey:"
echo "  python3 ${SCRIPT_DIR}/jarvis-voice.py --test-hotkey"
echo ""
echo "To start as daemon:"
echo "  launchctl load ${PLIST_PATH}"
echo ""
echo "To stop daemon:"
echo "  launchctl unload ${PLIST_PATH}"
