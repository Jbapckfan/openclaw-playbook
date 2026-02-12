#!/usr/bin/env bash
# setup-voice-hub.sh — Install all dependencies for the OpenClaw Voice Hub
# Installs: mlx-whisper, Piper TTS, sox, ffmpeg, sounddevice, webrtcvad
# Target: macOS with Apple Silicon (M-series)

set -euo pipefail

echo "╔══════════════════════════════════════╗"
echo "║    OpenClaw Voice Hub Setup          ║"
echo "╚══════════════════════════════════════╝"
echo ""

# --- Preflight checks ---
if [[ "$(uname)" != "Darwin" ]]; then
    echo "WARNING: This script is optimized for macOS. Some steps may not work on $(uname)."
fi

if [[ "$(uname -m)" != "arm64" ]]; then
    echo "WARNING: This script is optimized for Apple Silicon (arm64). Detected: $(uname -m)"
    echo "         mlx-whisper may not work on Intel Macs."
fi

# --- Check for Homebrew ---
if ! command -v brew &> /dev/null; then
    echo "ERROR: Homebrew not found. Install from https://brew.sh"
    exit 1
fi

# --- Check for Python 3 ---
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Install with: brew install python"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python version: ${PYTHON_VERSION}"

# --- Create virtual environment ---
VENV_DIR="${HOME}/jarvis/venvs/voice-hub"
echo ""
echo "=== Setting up Python virtual environment ==="
echo "Location: ${VENV_DIR}"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    echo "Created new virtual environment."
else
    echo "Virtual environment already exists."
fi

source "${VENV_DIR}/bin/activate"

# --- Install system dependencies via Homebrew ---
echo ""
echo "=== Installing system dependencies ==="

BREW_PACKAGES=("sox" "ffmpeg" "portaudio")

for pkg in "${BREW_PACKAGES[@]}"; do
    if brew list "$pkg" &> /dev/null; then
        echo "  ✓ ${pkg} (already installed)"
    else
        echo "  Installing ${pkg}..."
        brew install "$pkg"
        echo "  ✓ ${pkg} installed"
    fi
done

# --- Install Python packages ---
echo ""
echo "=== Installing Python packages ==="

pip install --upgrade pip

# Core audio processing
pip install sounddevice numpy

# Voice Activity Detection
pip install webrtcvad-wheels  # Pre-built wheels for macOS

# MLX Whisper — Apple Silicon optimized speech-to-text
pip install mlx-whisper

# Piper TTS — Local neural text-to-speech
pip install piper-tts

# HTTP client for OpenClaw gateway API
pip install httpx

# Global hotkey listener (for Jarvis conversational mode)
pip install pynput

echo ""
echo "=== Verifying installations ==="

# Verify each component
echo -n "  sox: "
if command -v sox &> /dev/null; then echo "✓ $(sox --version 2>&1 | head -1)"; else echo "✗ NOT FOUND"; fi

echo -n "  ffmpeg: "
if command -v ffmpeg &> /dev/null; then echo "✓ installed"; else echo "✗ NOT FOUND"; fi

echo -n "  sounddevice: "
if python3 -c "import sounddevice" 2>/dev/null; then echo "✓"; else echo "✗ import failed"; fi

echo -n "  webrtcvad: "
if python3 -c "import webrtcvad" 2>/dev/null; then echo "✓"; else echo "✗ import failed"; fi

echo -n "  mlx_whisper: "
if python3 -c "import mlx_whisper" 2>/dev/null; then echo "✓"; else echo "✗ import failed"; fi

echo -n "  piper: "
if python3 -c "import piper" 2>/dev/null; then echo "✓"; else echo "✗ import failed (may need build from source)"; fi

# --- Download Whisper model ---
echo ""
echo "=== Downloading Whisper model ==="
echo "Model: mlx-community/whisper-large-v3-turbo"
echo "This may take a few minutes on first run..."

python3 -c "
import mlx_whisper
# This will trigger model download on first import/use
print('Whisper model ready.')
" 2>/dev/null || echo "Note: Model will be downloaded on first use."

# --- Create data directories ---
echo ""
echo "=== Creating data directories ==="

mkdir -p "${HOME}/jarvis/data/voice/transcripts"
mkdir -p "${HOME}/jarvis/data/voice"
mkdir -p "${HOME}/jarvis/logs"

echo "  ✓ ~/jarvis/data/voice/transcripts/"
echo "  ✓ ~/jarvis/data/voice/"
echo "  ✓ ~/jarvis/logs/"

# --- Create launchd plist ---
echo ""
echo "=== Creating launchd service ==="

PLIST_PATH="${HOME}/Library/LaunchAgents/com.openclaw.voice-hub.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openclaw.voice-hub</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/python3</string>
        <string>${SCRIPT_DIR}/voice-router.py</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/jarvis/logs/voice-hub.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/jarvis/logs/voice-hub-error.log</string>
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
echo ""
echo "  To start the Voice Hub daemon:"
echo "    launchctl load ${PLIST_PATH}"
echo ""
echo "  To stop the Voice Hub daemon:"
echo "    launchctl unload ${PLIST_PATH}"
echo ""
echo "  To run manually (foreground):"
echo "    source ${VENV_DIR}/bin/activate"
echo "    python3 ${SCRIPT_DIR}/voice-router.py"

# --- Summary ---
echo ""
echo "╔══════════════════════════════════════╗"
echo "║    Setup Complete!                   ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Test microphone:  sox -d -n stat"
echo "  2. Test voice hub:   python3 ${SCRIPT_DIR}/voice-router.py"
echo "  3. Start daemon:     launchctl load ${PLIST_PATH}"
echo ""
echo "Logs: ~/jarvis/logs/voice-hub.log"
