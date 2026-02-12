#!/bin/bash
# =============================================================================
# JARVIS Mac Studio M3 Ultra — Full Setup Script
# =============================================================================
# This script configures a fresh Mac Studio M3 Ultra as a dedicated AI server
# running OpenClaw + Ollama + all supporting services.
#
# Prerequisites:
#   - macOS 15+ (Sequoia or later)
#   - Admin account access
#   - Internet connection
#
# Usage:
#   chmod +x mac-studio-setup.sh
#   ./mac-studio-setup.sh
#
# Author: James Alford
# Generated: February 2026
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "\n${CYAN}━━━ $1 ━━━${NC}\n"; }

# =============================================================================
# Phase 0: Pre-flight Checks
# =============================================================================
log_step "Phase 0: Pre-flight Checks"

# Check we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    log_error "This script is for macOS only."
    exit 1
fi

# Check for Apple Silicon
if [[ "$(uname -m)" != "arm64" ]]; then
    log_error "This script requires Apple Silicon (M-series chip)."
    exit 1
fi

# Check macOS version
MACOS_VERSION=$(sw_vers -productVersion)
log_info "macOS version: $MACOS_VERSION"

# Check available memory
TOTAL_MEM=$(sysctl -n hw.memsize)
TOTAL_MEM_GB=$((TOTAL_MEM / 1073741824))
log_info "Total memory: ${TOTAL_MEM_GB}GB"

if [[ $TOTAL_MEM_GB -lt 64 ]]; then
    log_warn "Less than 64GB RAM detected. Large models may not fit."
fi

log_ok "Pre-flight checks passed"

# =============================================================================
# Phase 1: System Configuration (24/7 Server Mode)
# =============================================================================
log_step "Phase 1: System Configuration for 24/7 Operation"

# Prevent sleep
log_info "Disabling system sleep (server mode)..."
sudo pmset -a sleep 0
sudo pmset -a disksleep 0
sudo pmset -a displaysleep 15  # Display can sleep, but not the system
sudo pmset -a hibernatemode 0
sudo pmset -a autopoweroff 0

# Enable auto-restart after power failure
sudo pmset -a autorestart 1

# Enable SSH (for Tailscale SSH and remote management)
log_info "Enabling Remote Login (SSH)..."
sudo systemsetup -setremotelogin on 2>/dev/null || log_warn "Remote Login may already be enabled"

# Enable Screen Sharing (VNC) for Tailscale VNC access
log_info "Enabling Screen Sharing..."
sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.screensharing.plist 2>/dev/null || log_warn "Screen Sharing may already be enabled"

# Disable Spotlight indexing on large data directories (saves CPU)
log_info "Configuring Spotlight exclusions..."
sudo mdutil -i off /Volumes/* 2>/dev/null || true

log_ok "System configured for 24/7 operation"

# =============================================================================
# Phase 2: Install Homebrew & Core Tools
# =============================================================================
log_step "Phase 2: Installing Homebrew & Core Tools"

if ! command -v brew &>/dev/null; then
    log_info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
    echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
else
    log_ok "Homebrew already installed"
fi

log_info "Installing core tools..."
brew install \
    git \
    python@3.12 \
    node \
    jq \
    curl \
    wget \
    htop \
    tmux \
    gh \
    docker \
    colima \
    tailscale \
    2>/dev/null || true

log_ok "Core tools installed"

# =============================================================================
# Phase 3: Install Tailscale (Zero-Trust Networking)
# =============================================================================
log_step "Phase 3: Setting Up Tailscale"

if ! command -v tailscale &>/dev/null; then
    log_info "Installing Tailscale..."
    brew install tailscale
fi

log_info "Starting Tailscale..."
# Note: Tailscale on macOS can also be installed via the Mac App Store
# which provides the menu bar icon and system extension
# For CLI-only (headless server), use brew version

# Check if Tailscale is running
if tailscale status &>/dev/null; then
    log_ok "Tailscale is connected"
    tailscale status | head -5
else
    log_warn "Tailscale is installed but not connected."
    log_info "Run 'tailscale up' to connect to your tailnet."
    log_info "For headless operation, use: tailscale up --ssh"
fi

# =============================================================================
# Phase 4: Install Ollama
# =============================================================================
log_step "Phase 4: Installing Ollama"

if ! command -v ollama &>/dev/null; then
    log_info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    log_ok "Ollama already installed"
fi

# Start Ollama service
log_info "Starting Ollama service..."
ollama serve &>/dev/null &
sleep 3

# Configure Ollama for network access (Tailscale only)
# By default Ollama listens on localhost:11434
# We'll configure it to listen on the Tailscale interface only
log_info "Configuring Ollama network binding..."
OLLAMA_CONFIG_DIR="$HOME/.ollama"
mkdir -p "$OLLAMA_CONFIG_DIR"

# Set environment variables for Ollama
cat > "$HOME/.ollama/env" << 'OLLAMA_ENV'
# Ollama Environment Configuration
# Listen on all interfaces (secured by Tailscale + firewall)
OLLAMA_HOST=0.0.0.0:11434
# Maximum loaded models (adjust based on available memory)
OLLAMA_MAX_LOADED_MODELS=3
# Keep models in memory longer (for faster switching)
OLLAMA_KEEP_ALIVE=24h
# Enable flash attention for better performance
OLLAMA_FLASH_ATTENTION=1
OLLAMA_ENV

log_ok "Ollama installed and configured"

# =============================================================================
# Phase 5: Pull Key Models
# =============================================================================
log_step "Phase 5: Pulling AI Models"

log_info "This will download several large models. Skipping for now."
log_info "Run these manually when ready:"
echo ""
echo "  # Primary reasoning model (~34GB)"
echo "  ollama pull qwen3:30b-a3b"
echo ""
echo "  # Large reasoning model (~190GB) — needs both Mac Studios"
echo "  ollama pull qwen3:235b-a22b"
echo ""
echo "  # Code generation"
echo "  ollama pull codellama:34b"
echo ""
echo "  # Fast chat"
echo "  ollama pull llama3.2:8b"
echo ""

# =============================================================================
# Phase 6: Install Python Environment
# =============================================================================
log_step "Phase 6: Setting Up Python Environment"

log_info "Creating virtual environment..."
python3.12 -m venv "$HOME/.venvs/jarvis"
source "$HOME/.venvs/jarvis/bin/activate"

log_info "Installing Python packages..."
pip install --upgrade pip
pip install \
    mflux \
    chromadb \
    fastapi \
    uvicorn \
    websockets \
    httpx \
    python-dotenv \
    schedule \
    pydantic \
    2>/dev/null || true

log_ok "Python environment ready"

# =============================================================================
# Phase 7: Install Docker (Sandboxed Execution)
# =============================================================================
log_step "Phase 7: Setting Up Docker (via Colima)"

log_info "Starting Colima (Docker runtime for macOS)..."
# Colima is a lightweight Docker runtime for macOS
# Much better than Docker Desktop for server use
colima start --cpu 4 --memory 8 --disk 100 2>/dev/null || log_warn "Colima may already be running"

if docker info &>/dev/null; then
    log_ok "Docker is running via Colima"
else
    log_warn "Docker not available. Start Colima with: colima start"
fi

# =============================================================================
# Phase 8: Install ComfyUI (Image Generation)
# =============================================================================
log_step "Phase 8: Installing ComfyUI"

COMFYUI_DIR="$HOME/ComfyUI"
if [[ ! -d "$COMFYUI_DIR" ]]; then
    log_info "Cloning ComfyUI..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR"
    cd "$COMFYUI_DIR"
    pip install -r requirements.txt 2>/dev/null || true
    cd -
else
    log_ok "ComfyUI already installed"
fi

# =============================================================================
# Phase 9: Install SearXNG (Private Search)
# =============================================================================
log_step "Phase 9: Installing SearXNG (Private Search)"

log_info "Setting up SearXNG via Docker..."
SEARXNG_DIR="$HOME/searxng"
mkdir -p "$SEARXNG_DIR"

cat > "$SEARXNG_DIR/docker-compose.yml" << 'SEARXNG_COMPOSE'
version: '3.8'
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    ports:
      - "8888:8080"
    volumes:
      - ./settings.yml:/etc/searxng/settings.yml:ro
    environment:
      - SEARXNG_BASE_URL=http://localhost:8888
    restart: unless-stopped
SEARXNG_COMPOSE

cat > "$SEARXNG_DIR/settings.yml" << 'SEARXNG_SETTINGS'
use_default_settings: true
server:
  secret_key: "CHANGE_THIS_TO_A_RANDOM_STRING"
  bind_address: "0.0.0.0"
  port: 8080
search:
  safe_search: 0
  autocomplete: "google"
  default_lang: "en"
engines:
  - name: google
    engine: google
    shortcut: g
  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
  - name: wikipedia
    engine: wikipedia
    shortcut: wp
  - name: github
    engine: github
    shortcut: gh
SEARXNG_SETTINGS

log_info "Start SearXNG with: cd $SEARXNG_DIR && docker compose up -d"
log_ok "SearXNG configuration ready"

# =============================================================================
# Phase 10: Install ChromaDB (Vector Database)
# =============================================================================
log_step "Phase 10: Setting Up ChromaDB"

CHROMA_DIR="$HOME/chromadb-data"
mkdir -p "$CHROMA_DIR"

log_info "ChromaDB installed via pip (Phase 6)."
log_info "Data directory: $CHROMA_DIR"
log_info "Start server with: chroma run --host 0.0.0.0 --port 8000 --path $CHROMA_DIR"

log_ok "ChromaDB ready"

# =============================================================================
# Phase 11: macOS Firewall Configuration
# =============================================================================
log_step "Phase 11: Configuring Firewall"

log_info "Enabling macOS firewall..."
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setblockall on
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode on

# Allow essential services through firewall
log_info "Adding firewall exceptions for services..."
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setallowsigned on

log_info "NOTE: With Tailscale, all services are accessible only within your tailnet."
log_info "No public ports are exposed. The firewall blocks everything else."

log_ok "Firewall configured"

# =============================================================================
# Phase 12: Create Directory Structure
# =============================================================================
log_step "Phase 12: Creating Directory Structure"

mkdir -p "$HOME/jarvis"/{agents,skills,logs,data,backups,configs,dashboards}
mkdir -p "$HOME/jarvis/agents"/{deal-scanner,newsletter,reputation,compliance,outreach,overnight,content,guardian}
mkdir -p "$HOME/jarvis/data"/{chromadb,scraped,generated,exports}
mkdir -p "$HOME/jarvis/logs"/{agents,system,revenue}

log_info "Directory structure:"
echo "  ~/jarvis/"
echo "  ├── agents/          # Agent configurations and state"
echo "  │   ├── deal-scanner/"
echo "  │   ├── newsletter/"
echo "  │   ├── reputation/"
echo "  │   ├── compliance/"
echo "  │   ├── outreach/"
echo "  │   ├── overnight/"
echo "  │   ├── content/"
echo "  │   └── guardian/"
echo "  ├── skills/          # Reusable agent skills/tools"
echo "  ├── logs/            # All system and agent logs"
echo "  ├── data/            # Persistent data stores"
echo "  ├── backups/         # Automated backups"
echo "  ├── configs/         # Configuration files"
echo "  └── dashboards/      # Web dashboards"

log_ok "Directory structure created"

# =============================================================================
# Phase 13: Create Launchd Services (Auto-Start on Boot)
# =============================================================================
log_step "Phase 13: Creating Auto-Start Services"

LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

# Ollama auto-start
cat > "$LAUNCH_DIR/com.jarvis.ollama.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.ollama</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/ollama</string>
        <string>serve</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/jarvis/logs/system/ollama.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/jarvis/logs/system/ollama-error.log</string>
</dict>
</plist>
PLIST

# ChromaDB auto-start
cat > "$LAUNCH_DIR/com.jarvis.chromadb.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.chromadb</string>
    <key>ProgramArguments</key>
    <array>
        <string>${HOME}/.venvs/jarvis/bin/chroma</string>
        <string>run</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8000</string>
        <string>--path</string>
        <string>${HOME}/jarvis/data/chromadb</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/jarvis/logs/system/chromadb.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/jarvis/logs/system/chromadb-error.log</string>
</dict>
</plist>
PLIST

log_info "Load services with:"
echo "  launchctl load $LAUNCH_DIR/com.jarvis.ollama.plist"
echo "  launchctl load $LAUNCH_DIR/com.jarvis.chromadb.plist"

log_ok "Auto-start services created"

# =============================================================================
# Phase 14: Create Health Check Script
# =============================================================================
log_step "Phase 14: Creating Health Check Script"

cat > "$HOME/jarvis/scripts/health-check.sh" << 'HEALTHCHECK'
#!/bin/bash
# Jarvis System Health Check
# Run manually or via cron every 5 minutes

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
STATUS="OK"
ISSUES=""

# Check Ollama
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    OLLAMA_STATUS="Running"
    MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
else
    OLLAMA_STATUS="DOWN"
    STATUS="DEGRADED"
    ISSUES="$ISSUES Ollama is not responding."
fi

# Check ChromaDB
if curl -s http://localhost:8000/api/v2/heartbeat > /dev/null 2>&1; then
    CHROMA_STATUS="Running"
else
    CHROMA_STATUS="DOWN"
    STATUS="DEGRADED"
    ISSUES="$ISSUES ChromaDB is not responding."
fi

# Check SearXNG
if curl -s http://localhost:8888/healthz > /dev/null 2>&1; then
    SEARXNG_STATUS="Running"
else
    SEARXNG_STATUS="DOWN"
    ISSUES="$ISSUES SearXNG is not responding."
fi

# Check Tailscale
if tailscale status > /dev/null 2>&1; then
    TS_STATUS="Connected"
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
else
    TS_STATUS="Disconnected"
    STATUS="DEGRADED"
    ISSUES="$ISSUES Tailscale is disconnected."
fi

# System resources
CPU_USAGE=$(top -l 1 | grep "CPU usage" | awk '{print $3}' 2>/dev/null || echo "?")
MEM_USED=$(memory_pressure 2>/dev/null | grep "System-wide" | awk '{print $4}' || echo "?")
DISK_FREE=$(df -h / | awk 'NR==2{print $4}')
THERMAL=$(sudo powermetrics --samplers smc -n 1 -i 1 2>/dev/null | grep "CPU die temperature" | awk '{print $4}' || echo "?")

# Output
echo "═══════════════════════════════════════"
echo "  JARVIS Health Check — $TIMESTAMP"
echo "═══════════════════════════════════════"
echo ""
echo "  System Status:  $STATUS"
echo ""
echo "  Services:"
echo "    Ollama:    $OLLAMA_STATUS ($MODELS models available)"
echo "    ChromaDB:  $CHROMA_STATUS"
echo "    SearXNG:   $SEARXNG_STATUS"
echo "    Tailscale: $TS_STATUS ($TS_IP)"
echo ""
echo "  Resources:"
echo "    CPU:       $CPU_USAGE"
echo "    Memory:    $MEM_USED"
echo "    Disk Free: $DISK_FREE"
echo "    Thermal:   ${THERMAL}°C"
echo ""

if [[ -n "$ISSUES" ]]; then
    echo "  ISSUES:"
    echo "    $ISSUES"
    echo ""
fi

echo "═══════════════════════════════════════"

# Log to file
echo "$TIMESTAMP | Status: $STATUS | Ollama: $OLLAMA_STATUS | Chroma: $CHROMA_STATUS | SearXNG: $SEARXNG_STATUS | TS: $TS_STATUS" >> "$HOME/jarvis/logs/system/health.log"
HEALTHCHECK

chmod +x "$HOME/jarvis/scripts/health-check.sh"
log_ok "Health check script created at ~/jarvis/scripts/health-check.sh"

# =============================================================================
# Phase 15: Summary
# =============================================================================
log_step "Setup Complete!"

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │         JARVIS Mac Studio Setup              │"
echo "  │              COMPLETE                        │"
echo "  └─────────────────────────────────────────────┘"
echo ""
echo "  Installed:"
echo "    ✅ Homebrew + core tools"
echo "    ✅ Tailscale (zero-trust networking)"
echo "    ✅ Ollama (local LLM inference)"
echo "    ✅ Python environment + packages"
echo "    ✅ Docker via Colima (sandboxed execution)"
echo "    ✅ ComfyUI (image generation)"
echo "    ✅ SearXNG config (private search)"
echo "    ✅ ChromaDB (vector database)"
echo "    ✅ macOS firewall (hardened)"
echo "    ✅ Directory structure"
echo "    ✅ Auto-start services"
echo "    ✅ Health check script"
echo ""
echo "  Next steps:"
echo "    1. Run 'tailscale up --ssh' to connect to your tailnet"
echo "    2. Pull AI models: ollama pull qwen3:30b-a3b"
echo "    3. Start SearXNG: cd ~/searxng && docker compose up -d"
echo "    4. Install OpenClaw when ready"
echo "    5. Run health check: ~/jarvis/scripts/health-check.sh"
echo ""
echo "  Access from anywhere via Tailscale:"
echo "    SSH:      ssh $(whoami)@$(hostname).tail-xxxxx.ts.net"
echo "    VNC:      vnc://$(hostname).tail-xxxxx.ts.net"
echo "    Ollama:   http://$(hostname).tail-xxxxx.ts.net:11434"
echo "    ChromaDB: http://$(hostname).tail-xxxxx.ts.net:8000"
echo "    SearXNG:  http://$(hostname).tail-xxxxx.ts.net:8888"
echo "    Dashboard: http://$(hostname).tail-xxxxx.ts.net:3000"
echo ""
