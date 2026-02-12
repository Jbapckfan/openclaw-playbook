#!/usr/bin/env bash
# setup-3d-pipeline.sh — Install all dependencies for the idea-to-print pipeline
# Target: Mac Studio M3 Ultra (Apple Silicon)
set -euo pipefail

VENV_DIR="$HOME/jarvis/envs/3d-pipeline"
TRIPOSR_DIR="$HOME/jarvis/models/TripoSR"
DATA_DIR="$HOME/jarvis/data/prints"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
fail() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

echo "═══════════════════════════════════════════════════"
echo "  Idea → Print Pipeline — Setup Script"
echo "  Target: Mac Studio M3 Ultra / Apple Silicon"
echo "═══════════════════════════════════════════════════"
echo ""

# ─── Prerequisites ──────────────────────────────────────────────────────────

echo "── Checking prerequisites ──"

command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install via: brew install python@3.11"
command -v git     >/dev/null 2>&1 || fail "git not found. Install via: brew install git"
command -v brew    >/dev/null 2>&1 || fail "Homebrew not found. Install from https://brew.sh"

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
log "Python $PYTHON_VERSION found"

# Check for Apple Silicon
ARCH=$(uname -m)
if [ "$ARCH" != "arm64" ]; then
    warn "Expected arm64 (Apple Silicon), got $ARCH. MPS acceleration may not work."
fi

# ─── Create directories ────────────────────────────────────────────────────

echo ""
echo "── Creating directories ──"

mkdir -p "$VENV_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$HOME/jarvis/models"
log "Created $VENV_DIR"
log "Created $DATA_DIR"

# ─── Python venv ────────────────────────────────────────────────────────────

echo ""
echo "── Setting up Python virtual environment ──"

if [ -d "$VENV_DIR/bin" ]; then
    warn "Venv already exists at $VENV_DIR — reusing"
else
    python3 -m venv "$VENV_DIR"
    log "Created venv at $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel -q
log "Upgraded pip/setuptools/wheel"

# ─── PyTorch (MPS-enabled for Apple Silicon) ────────────────────────────────

echo ""
echo "── Installing PyTorch (MPS-enabled) ──"

pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu -q 2>/dev/null \
    || pip install torch torchvision -q

# Verify MPS availability
python3 -c "
import torch
if torch.backends.mps.is_available():
    print('[✓] PyTorch MPS backend available')
else:
    print('[!] MPS not available — will fall back to CPU')
print(f'    PyTorch version: {torch.__version__}')
"

# ─── Python dependencies ────────────────────────────────────────────────────

echo ""
echo "── Installing Python dependencies ──"

pip install -r "$SCRIPT_DIR/requirements-3d.txt" -q
log "Installed requirements from requirements-3d.txt"

# ─── TripoSR ────────────────────────────────────────────────────────────────

echo ""
echo "── Installing TripoSR ──"

if [ -d "$TRIPOSR_DIR" ]; then
    warn "TripoSR already cloned at $TRIPOSR_DIR — pulling latest"
    cd "$TRIPOSR_DIR" && git pull -q && cd -
else
    git clone https://github.com/VAST-AI-Research/TripoSR.git "$TRIPOSR_DIR"
    log "Cloned TripoSR to $TRIPOSR_DIR"
fi

# Install TripoSR dependencies
cd "$TRIPOSR_DIR"
if [ -f requirements.txt ]; then
    pip install -r requirements.txt -q 2>/dev/null || warn "Some TripoSR deps failed — non-critical"
fi

# Install torchmcubes (CPU fallback for marching cubes on non-CUDA)
pip install git+https://github.com/tatsy/torchmcubes.git -q 2>/dev/null \
    || warn "torchmcubes install failed — will use trimesh marching cubes fallback"

cd "$SCRIPT_DIR/.."
log "TripoSR installed"

# ─── Download TripoSR model weights ────────────────────────────────────────

echo ""
echo "── Downloading TripoSR model weights ──"

python3 -c "
from huggingface_hub import snapshot_download
import os

cache_dir = os.path.expanduser('~/jarvis/models/triposr-weights')
if os.path.exists(cache_dir) and os.listdir(cache_dir):
    print('[!] TripoSR weights already downloaded — skipping')
else:
    print('    Downloading stabilityai/TripoSR (~1.5GB)...')
    snapshot_download(
        repo_id='stabilityai/TripoSR',
        local_dir=cache_dir,
    )
    print('[✓] TripoSR weights downloaded')
" 2>/dev/null || {
    warn "Auto-download failed. Weights will download on first run."
    pip install huggingface_hub -q
}

# ─── OrcaSlicer ─────────────────────────────────────────────────────────────

echo ""
echo "── Checking OrcaSlicer ──"

ORCASLICER_APP="/Applications/OrcaSlicer.app"
BAMBU_STUDIO_APP="/Applications/BambuStudio.app"

if [ -d "$ORCASLICER_APP" ]; then
    log "OrcaSlicer found at $ORCASLICER_APP"
elif [ -d "$BAMBU_STUDIO_APP" ]; then
    warn "OrcaSlicer not found, but Bambu Studio found — will use as fallback"
else
    warn "No slicer found. Install OrcaSlicer:"
    echo "    brew install --cask orcaslicer"
    echo "    — or download from https://github.com/SoftFever/OrcaSlicer/releases"
    echo ""
    read -p "Install OrcaSlicer via Homebrew now? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        brew install --cask orcaslicer
        log "OrcaSlicer installed"
    else
        warn "Skipping OrcaSlicer install — you'll need to install it manually"
    fi
fi

# ─── Verify mflux ──────────────────────────────────────────────────────────

echo ""
echo "── Checking mflux (FLUX.1 image generation) ──"

if command -v mflux-generate >/dev/null 2>&1; then
    log "mflux-generate found"
elif pip show mflux >/dev/null 2>&1; then
    log "mflux installed in venv"
else
    warn "mflux not found. Installing..."
    pip install mflux -q 2>/dev/null || warn "mflux install failed — install manually: pip install mflux"
fi

# ─── Verify Ollama ─────────────────────────────────────────────────────────

echo ""
echo "── Checking Ollama ──"

if command -v ollama >/dev/null 2>&1; then
    log "Ollama found"
    if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
        log "Ollama server is running"
    else
        warn "Ollama installed but server not running. Start with: ollama serve"
    fi
else
    warn "Ollama not found. Install from https://ollama.com"
fi

# ─── Smoke test ─────────────────────────────────────────────────────────────

echo ""
echo "── Running smoke test ──"

python3 -c "
import sys

print('  Checking imports...')
errors = []

try:
    import torch
    print(f'    torch {torch.__version__} — OK')
except ImportError as e:
    errors.append(f'torch: {e}')

try:
    import trimesh
    print(f'    trimesh {trimesh.__version__} — OK')
except ImportError as e:
    errors.append(f'trimesh: {e}')

try:
    import pymeshlab
    print(f'    pymeshlab — OK')
except ImportError as e:
    errors.append(f'pymeshlab: {e}')

try:
    import PIL
    print(f'    Pillow {PIL.__version__} — OK')
except ImportError as e:
    errors.append(f'Pillow: {e}')

try:
    import transformers
    print(f'    transformers {transformers.__version__} — OK')
except ImportError as e:
    errors.append(f'transformers: {e}')

try:
    import httpx
    print(f'    httpx {httpx.__version__} — OK')
except ImportError as e:
    errors.append(f'httpx: {e}')

# Test trimesh mesh creation
try:
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    assert mesh.is_watertight, 'Test cube is not watertight'
    stl_path = '$DATA_DIR/smoke_test.stl'
    mesh.export(stl_path)
    print(f'    Smoke test cube exported to {stl_path} — OK')
except Exception as e:
    errors.append(f'mesh test: {e}')

if errors:
    print(f'\\n  Errors ({len(errors)}):')
    for err in errors:
        print(f'    [✗] {err}')
    sys.exit(1)
else:
    print('\\n  All checks passed!')
"

# ─── Summary ────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Venv:      $VENV_DIR"
echo "  TripoSR:   $TRIPOSR_DIR"
echo "  Output:    $DATA_DIR"
echo ""
echo "  Activate venv:"
echo "    source $VENV_DIR/bin/activate"
echo ""
echo "  Run the pipeline:"
echo "    python3 scripts/idea-to-print.py --idea \"a small bowl\""
echo ""
