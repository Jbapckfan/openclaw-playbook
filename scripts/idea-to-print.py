#!/usr/bin/env python3
"""
idea-to-print.py — Idea → Image → 3D → Bambu Lab X1C Print Pipeline

Semi-automated pipeline that:
  1. Refines a text idea into a FLUX.1 prompt (Ollama)
  2. Generates a reference image (mflux / FLUX.1)
  3. Converts the image to a 3D mesh (TripoSR)
  4. Repairs the mesh for FDM printing (PyMeshLab + trimesh)
  5. Opens the result in OrcaSlicer for manual review

Usage:
  python3 idea-to-print.py                                    # Interactive mode
  python3 idea-to-print.py --idea "a desk organizer"          # From idea
  python3 idea-to-print.py --image output/ref.png             # From image
  python3 idea-to-print.py --mesh output/raw.obj              # Repair only
  python3 idea-to-print.py --idea "phone stand" --width 80 --height 120 --depth 60
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ─── Configuration ──────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:30b-a3b"
TRIPOSR_DIR = Path.home() / "jarvis" / "models" / "TripoSR"
OUTPUT_BASE = Path.home() / "jarvis" / "data" / "prints"
ORCASLICER_APP = "/Applications/OrcaSlicer.app"
BAMBU_STUDIO_APP = "/Applications/BambuStudio.app"

# Image generation defaults
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024
IMAGE_STEPS = 30
MFLUX_MODEL = "dev"

# 3D generation defaults
TRIPOSR_RESOLUTION = 256  # Marching cubes resolution

# Mesh repair defaults
MAX_HOLE_SIZE = 100  # Max edges to close in hole-filling
DEFAULT_TARGET_MM = {"width": 100, "height": 100, "depth": 100}


# ─── Utilities ──────────────────────────────────────────────────────────────

class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    BLUE = "\033[0;34m"
    BOLD = "\033[1m"
    NC = "\033[0m"


def log_stage(stage_num: int, title: str):
    print(f"\n{Colors.BOLD}{'═' * 60}{Colors.NC}")
    print(f"{Colors.BOLD}  STAGE {stage_num}: {title}{Colors.NC}")
    print(f"{Colors.BOLD}{'═' * 60}{Colors.NC}\n")


def log_ok(msg: str):
    print(f"{Colors.GREEN}[OK]{Colors.NC} {msg}")


def log_warn(msg: str):
    print(f"{Colors.YELLOW}[!!]{Colors.NC} {msg}")


def log_err(msg: str):
    print(f"{Colors.RED}[ERR]{Colors.NC} {msg}")


def log_info(msg: str):
    print(f"{Colors.BLUE}[..]{Colors.NC} {msg}")


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:50]


def make_output_dir(idea: str) -> Path:
    """Create a timestamped output directory for this run."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify(idea) if idea else "pipeline"
    out_dir = OUTPUT_BASE / f"{timestamp}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def confirm(prompt: str, default: bool = True) -> bool:
    """Ask user for y/n confirmation."""
    suffix = "[Y/n]" if default else "[y/N]"
    response = input(f"{prompt} {suffix} ").strip().lower()
    if not response:
        return default
    return response in ("y", "yes")


# ─── Stage 1: Idea → Prompt (Ollama) ───────────────────────────────────────

PROMPT_SYSTEM = """You are an industrial designer specializing in 3D-printable objects.
Given an idea, generate a structured JSON response with:

1. "prompt" — A FLUX.1 image generation prompt optimized for 3D reconstruction.
   MUST include: isolated object, white background, three-quarter view,
   product photography, studio lighting, sharp focus, high detail.
   MUST NOT include: motion blur, bokeh, multiple objects, text overlays.

2. "dimensions_mm" — Suggested dimensions as {"width": N, "height": N, "depth": N} in millimeters.

3. "print_notes" — Array of strings noting potential FDM printing issues
   (overhangs >45°, thin walls <1.5mm, bridges >10mm, etc.)

4. "orientation_hint" — Recommended print orientation.

Return ONLY valid JSON. No markdown fences, no explanation outside the JSON."""


def refine_prompt(idea: str) -> dict:
    """Call Ollama to refine an idea into a structured prompt."""
    import httpx

    log_info(f"Asking {OLLAMA_MODEL} to refine: \"{idea}\"")

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": f"Design a 3D-printable object: {idea}"},
        ],
        "stream": False,
        "options": {"temperature": 0.6},
    }

    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=120.0,
        )
        resp.raise_for_status()
    except httpx.ConnectError:
        log_err("Cannot connect to Ollama. Is it running? (ollama serve)")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        log_err(f"Ollama returned {e.response.status_code}")
        sys.exit(1)

    content = resp.json()["message"]["content"]

    # Strip markdown code fences if present
    content = re.sub(r"```json\s*", "", content)
    content = re.sub(r"```\s*", "", content)
    content = content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        log_warn("Ollama didn't return valid JSON. Using raw text as prompt.")
        result = {
            "prompt": content,
            "dimensions_mm": DEFAULT_TARGET_MM.copy(),
            "print_notes": [],
            "orientation_hint": "Unknown — review manually",
        }

    return result


def show_prompt(prompt_data: dict, out_dir: Path) -> dict:
    """Display the refined prompt and let user edit."""
    print(f"\n{Colors.BOLD}Image Prompt:{Colors.NC}")
    print(f"  {prompt_data.get('prompt', 'N/A')}")

    dims = prompt_data.get("dimensions_mm", {})
    print(f"\n{Colors.BOLD}Suggested Dimensions:{Colors.NC}")
    print(f"  {dims.get('width', '?')}mm W x {dims.get('height', '?')}mm H x {dims.get('depth', '?')}mm D")

    notes = prompt_data.get("print_notes", [])
    if notes:
        print(f"\n{Colors.BOLD}Print Notes:{Colors.NC}")
        for note in notes:
            print(f"  - {note}")

    hint = prompt_data.get("orientation_hint", "")
    if hint:
        print(f"\n{Colors.BOLD}Orientation:{Colors.NC} {hint}")

    # Save prompt to file
    prompt_file = out_dir / "prompt.txt"
    prompt_file.write_text(prompt_data.get("prompt", ""))
    (out_dir / "prompt_full.json").write_text(json.dumps(prompt_data, indent=2))

    # Allow editing
    print("")
    if not confirm("Use this prompt?"):
        new_prompt = input("Enter your prompt (or press Enter to keep): ").strip()
        if new_prompt:
            prompt_data["prompt"] = new_prompt
            prompt_file.write_text(new_prompt)
            log_ok("Prompt updated")

    return prompt_data


# ─── Stage 2: Prompt → Image (mflux / FLUX.1) ─────────────────────────────

# Suffix appended to every prompt for better 3D reconstruction
IMAGE_PROMPT_SUFFIX = (
    ", isolated object, white background, product photography, "
    "three-quarter view, sharp focus, studio lighting, high detail, matte finish"
)


def generate_image(prompt: str, out_dir: Path) -> Path:
    """Generate a reference image using mflux (FLUX.1)."""
    image_path = out_dir / "reference.png"

    # Append 3D-friendly suffix if not already present
    full_prompt = prompt
    if "isolated object" not in prompt.lower():
        full_prompt = prompt.rstrip(", ") + IMAGE_PROMPT_SUFFIX

    log_info(f"Generating image ({IMAGE_WIDTH}x{IMAGE_HEIGHT}, {IMAGE_STEPS} steps)...")

    # Check for mflux
    mflux_cmd = shutil.which("mflux-generate")
    if not mflux_cmd:
        # Try within venv
        venv_mflux = Path.home() / "jarvis" / "envs" / "3d-pipeline" / "bin" / "mflux-generate"
        if venv_mflux.exists():
            mflux_cmd = str(venv_mflux)
        else:
            log_err("mflux-generate not found. Install with: pip install mflux")
            sys.exit(1)

    cmd = [
        mflux_cmd,
        "--model", MFLUX_MODEL,
        "--prompt", full_prompt,
        "--steps", str(IMAGE_STEPS),
        "--width", str(IMAGE_WIDTH),
        "--height", str(IMAGE_HEIGHT),
        "--output", str(image_path),
    ]

    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - start

    if result.returncode != 0:
        log_err(f"mflux failed:\n{result.stderr}")
        sys.exit(1)

    if not image_path.exists():
        # mflux may use a different naming convention
        possible = list(out_dir.glob("*.png"))
        if possible:
            image_path = possible[0]
            log_warn(f"Image saved as {image_path.name} instead of reference.png")
        else:
            log_err("No image file produced by mflux")
            sys.exit(1)

    log_ok(f"Image generated in {elapsed:.1f}s → {image_path}")
    return image_path


def show_image(image_path: Path):
    """Open the image for user review."""
    log_info("Opening image for review...")
    subprocess.run(["open", str(image_path)], check=False)
    print("")
    if not confirm("Image looks good? Continue to 3D generation?"):
        log_warn("Aborting. You can re-run with --image to skip to 3D generation.")
        sys.exit(0)


# ─── Stage 3: Image → 3D Mesh (TripoSR) ───────────────────────────────────

def generate_3d(image_path: Path, out_dir: Path) -> Path:
    """Convert a 2D image to a 3D mesh using TripoSR."""
    mesh_path = out_dir / "raw_mesh.obj"

    # Try TripoSR first
    if _try_triposr(image_path, mesh_path):
        return mesh_path

    # Fallback: try Hunyuan3D-2 via Pinokio
    if _try_hunyuan3d(image_path, mesh_path):
        return mesh_path

    log_err("No 3D generation backend available.")
    log_err("Install TripoSR: bash scripts/setup-3d-pipeline.sh")
    sys.exit(1)


def _try_triposr(image_path: Path, mesh_path: Path) -> bool:
    """Attempt 3D generation with TripoSR."""
    try:
        import torch
        from PIL import Image
    except ImportError:
        log_warn("torch/PIL not available for TripoSR")
        return False

    # Check if TripoSR is available
    triposr_run = TRIPOSR_DIR / "run.py"
    if not triposr_run.exists():
        # Try the API approach — load model directly
        return _triposr_api(image_path, mesh_path)

    log_info("Running TripoSR (this may take 30-60 seconds on CPU)...")
    start = time.time()

    cmd = [
        sys.executable,
        str(triposr_run),
        str(image_path),
        "--output-dir", str(mesh_path.parent),
        "--model-save-format", "obj",
        "--render",
    ]

    # Set device to cpu since MPS has limited op support for TripoSR
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""

    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(TRIPOSR_DIR))
    elapsed = time.time() - start

    if result.returncode != 0:
        log_warn(f"TripoSR run.py failed: {result.stderr[:500]}")
        # Try API approach as fallback
        return _triposr_api(image_path, mesh_path)

    # TripoSR may output to a subdirectory — find the OBJ
    for obj_file in mesh_path.parent.rglob("*.obj"):
        if obj_file != mesh_path:
            shutil.move(str(obj_file), str(mesh_path))
            break

    if mesh_path.exists():
        log_ok(f"3D mesh generated in {elapsed:.1f}s → {mesh_path}")
        return True

    log_warn("TripoSR run.py completed but no OBJ found")
    return False


def _triposr_api(image_path: Path, mesh_path: Path) -> bool:
    """Load TripoSR model directly via transformers API."""
    try:
        import torch
        from PIL import Image

        log_info("Loading TripoSR model via API (first run downloads ~1.5GB)...")

        # Attempt to use the TSR model
        sys.path.insert(0, str(TRIPOSR_DIR))
        try:
            from tsr.system import TSR
        except ImportError:
            log_warn("TSR module not found in TripoSR directory")
            return False

        device = "cpu"  # MPS has limited ops support for this model
        log_info(f"Using device: {device}")

        model = TSR.from_pretrained(
            "stabilityai/TripoSR",
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        model.renderer.set_chunk_size(8192)
        model.to(device)

        image = Image.open(image_path)

        log_info("Running inference...")
        start = time.time()

        with torch.no_grad():
            scene_codes = model([image], device=device)

        meshes = model.extract_mesh(scene_codes, resolution=TRIPOSR_RESOLUTION)
        meshes[0].export(str(mesh_path))
        elapsed = time.time() - start

        log_ok(f"3D mesh generated in {elapsed:.1f}s → {mesh_path}")
        return True

    except Exception as e:
        log_warn(f"TripoSR API approach failed: {e}")
        return False


def _try_hunyuan3d(image_path: Path, mesh_path: Path) -> bool:
    """Attempt 3D generation with Hunyuan3D-2 via Pinokio."""
    # Check if Pinokio Hunyuan3D endpoint is available
    try:
        import httpx
        resp = httpx.get("http://localhost:7860/api/predict", timeout=5.0)
        # If we get here, Gradio app is running
    except Exception:
        log_warn("Hunyuan3D-2 (Pinokio) not running — skipping")
        return False

    log_info("Hunyuan3D-2 detected. Running shape generation (2-5 minutes)...")
    log_warn("Hunyuan3D-2 integration via Pinokio requires manual setup.")
    log_warn("For now, use TripoSR as the primary 3D backend.")
    return False


# ─── Stage 4: Mesh Repair (PyMeshLab + trimesh) ────────────────────────────

def repair_mesh(
    mesh_path: Path,
    out_dir: Path,
    target_mm: dict | None = None,
) -> Path:
    """Repair a mesh to make it 3D-print ready."""
    import numpy as np
    import trimesh

    repaired_path = out_dir / "repaired_mesh.stl"
    target = target_mm or DEFAULT_TARGET_MM

    log_info(f"Loading mesh: {mesh_path}")
    mesh = trimesh.load(mesh_path, force="mesh")

    if not hasattr(mesh, "faces") or len(mesh.faces) == 0:
        log_err("Loaded file has no faces. Is this a valid 3D mesh?")
        sys.exit(1)

    log_info(f"Raw mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
    log_info(f"Watertight: {mesh.is_watertight}, Volume: {mesh.is_volume}")

    # ── PyMeshLab repair pass ──
    repaired = _pymeshlab_repair(mesh_path, out_dir)
    if repaired:
        mesh = trimesh.load(repaired, force="mesh")
        log_info("PyMeshLab repair pass completed")

    # ── trimesh repair pass ──
    log_info("Running trimesh repair pass...")

    # Remove degenerate faces
    mesh.remove_degenerate_faces()

    # Merge close vertices
    mesh.merge_vertices()

    # Remove duplicate faces
    mesh.remove_duplicate_faces()

    # Fix normals
    mesh.fix_normals()

    # Fill holes if possible
    if not mesh.is_watertight:
        log_info("Mesh not watertight — attempting hole fill...")
        trimesh.repair.fill_holes(mesh)

    # If still not watertight, try voxel remesh
    if not mesh.is_watertight:
        log_warn("Still not watertight — attempting voxel remesh...")
        try:
            pitch = mesh.extents.max() / 128.0
            voxelized = mesh.voxelized(pitch)
            mesh = voxelized.marching_cubes
            log_ok("Voxel remesh produced watertight mesh")
        except Exception as e:
            log_warn(f"Voxel remesh failed: {e}")

    # ── Scale to target dimensions ──
    log_info(f"Scaling to target: {target['width']}x{target['height']}x{target['depth']}mm")
    current_extents = mesh.extents  # [x, y, z]
    target_extents = np.array([target["width"], target["height"], target["depth"]])

    # Scale uniformly to fit within target bounding box
    scale_factor = (target_extents / current_extents).min()
    mesh.apply_scale(scale_factor)

    # Center on origin, place on build plate (z=0)
    mesh.vertices -= mesh.bounds[0]  # Move min corner to origin
    # Shift so bottom face sits at z=0
    mesh.vertices[:, 2] -= mesh.vertices[:, 2].min()

    # ── Export ──
    mesh.export(str(repaired_path))
    log_ok(f"Repaired mesh exported → {repaired_path}")

    return repaired_path


def _pymeshlab_repair(mesh_path: Path, out_dir: Path) -> Path | None:
    """Run PyMeshLab filter pipeline for mesh repair."""
    try:
        import pymeshlab
    except ImportError:
        log_warn("PyMeshLab not installed — skipping PyMeshLab repair pass")
        return None

    try:
        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(str(mesh_path))

        # Remove duplicate vertices
        ms.meshing_remove_duplicate_vertices()

        # Remove duplicate faces
        ms.meshing_remove_duplicate_faces()

        # Remove zero-area faces
        ms.meshing_remove_null_faces()

        # Repair non-manifold edges
        try:
            ms.meshing_repair_non_manifold_edges()
        except Exception:
            pass  # Some versions don't have this filter

        # Repair non-manifold vertices
        try:
            ms.meshing_repair_non_manifold_vertices()
        except Exception:
            pass

        # Close holes
        try:
            ms.meshing_close_holes(maxholesize=MAX_HOLE_SIZE)
        except Exception:
            pass

        # Re-orient faces coherently
        try:
            ms.meshing_re_orient_faces_coherently()
        except Exception:
            pass

        # Recompute normals
        try:
            ms.compute_normal_for_point_clouds()
        except Exception:
            pass

        pymeshlab_out = out_dir / "pymeshlab_repaired.obj"
        ms.save_current_mesh(str(pymeshlab_out))
        log_ok("PyMeshLab repair pass done")
        return pymeshlab_out

    except Exception as e:
        log_warn(f"PyMeshLab repair failed: {e}")
        return None


def print_mesh_stats(stl_path: Path):
    """Print statistics about the repaired mesh."""
    import trimesh

    mesh = trimesh.load(stl_path, force="mesh")

    extents = mesh.extents
    volume = mesh.volume if mesh.is_volume else 0

    print(f"\n{Colors.BOLD}Mesh Statistics:{Colors.NC}")
    print(f"  Vertices:    {len(mesh.vertices):,}")
    print(f"  Faces:       {len(mesh.faces):,}")
    print(f"  Dimensions:  {extents[0]:.1f} x {extents[1]:.1f} x {extents[2]:.1f} mm")
    print(f"  Volume:      {volume:.1f} mm\u00b3 ({volume / 1000:.1f} cm\u00b3)")
    print(f"  Watertight:  {'Yes' if mesh.is_watertight else 'NO — may cause slicing issues'}")
    print(f"  Is Volume:   {'Yes' if mesh.is_volume else 'NO'}")

    # Rough filament estimate (PLA at 1.24 g/cm³, 20% infill)
    if volume > 0:
        infill_fraction = 0.20
        wall_fraction = 0.15  # Approximate wall/top/bottom
        effective_volume = volume * (infill_fraction + wall_fraction)
        weight_g = effective_volume / 1000 * 1.24
        filament_m = weight_g / (1.24 * 3.14159 * (1.75 / 2) ** 2 / 1000)
        print(f"  Est. weight: ~{weight_g:.0f}g PLA (20% infill)")
        print(f"  Est. length: ~{filament_m:.1f}m filament")


# ─── Stage 5: Open Slicer ──────────────────────────────────────────────────

def open_in_slicer(stl_path: Path):
    """Open the repaired STL in OrcaSlicer or Bambu Studio."""
    slicer = None
    slicer_name = None

    if os.path.isdir(ORCASLICER_APP):
        slicer = ORCASLICER_APP
        slicer_name = "OrcaSlicer"
    elif os.path.isdir(BAMBU_STUDIO_APP):
        slicer = BAMBU_STUDIO_APP
        slicer_name = "Bambu Studio"

    if slicer:
        log_info(f"Opening in {slicer_name}...")
        subprocess.run(["open", "-a", slicer, str(stl_path)], check=False)
        log_ok(f"Opened {stl_path.name} in {slicer_name}")
        print(f"\n{Colors.BOLD}Next steps:{Colors.NC}")
        print("  1. Select your Bambu Lab X1C printer profile")
        print("  2. Adjust orientation and supports as needed")
        print("  3. Slice and review the preview")
        print("  4. Send to printer when satisfied")
    else:
        log_warn("No slicer found. Install OrcaSlicer:")
        log_warn("  brew install --cask orcaslicer")
        print(f"\n  Your STL is ready at: {stl_path}")


# ─── Metadata ───────────────────────────────────────────────────────────────

def save_metadata(out_dir: Path, idea: str, prompt_data: dict, timings: dict):
    """Save run metadata to JSON."""
    import trimesh

    stl_path = out_dir / "repaired_mesh.stl"
    mesh_info = {}
    if stl_path.exists():
        mesh = trimesh.load(stl_path, force="mesh")
        mesh_info = {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "dimensions_mm": {
                "width": round(mesh.extents[0], 1),
                "height": round(mesh.extents[1], 1),
                "depth": round(mesh.extents[2], 1),
            },
            "volume_mm3": round(mesh.volume, 1) if mesh.is_volume else None,
            "watertight": mesh.is_watertight,
        }

    metadata = {
        "idea": idea,
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt_data,
        "mesh": mesh_info,
        "timings": timings,
        "platform": {
            "os": platform.system(),
            "arch": platform.machine(),
            "python": platform.python_version(),
        },
    }

    meta_path = out_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    log_ok(f"Metadata saved → {meta_path}")


# ─── Main ───────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Idea → Image → 3D → Print pipeline for Bambu Lab X1C",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --idea "a desk organizer shaped like a dragon"
  %(prog)s --image ~/my_image.png
  %(prog)s --mesh ~/raw_model.obj --width 80 --height 120 --depth 60
        """,
    )
    parser.add_argument("--idea", type=str, help="Text description of what to print")
    parser.add_argument("--image", type=str, help="Skip to Stage 3 with existing image")
    parser.add_argument("--mesh", type=str, help="Skip to Stage 4 with existing mesh")
    parser.add_argument("--width", type=float, help="Target width in mm")
    parser.add_argument("--height", type=float, help="Target height in mm")
    parser.add_argument("--depth", type=float, help="Target depth in mm")
    parser.add_argument("--output", type=str, help="Override output directory")
    parser.add_argument("--no-slicer", action="store_true", help="Skip opening slicer")
    return parser.parse_args()


def main():
    args = parse_args()
    timings = {}
    prompt_data = {}

    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.NC}")
    print(f"{Colors.BOLD}  Idea → Print Pipeline{Colors.NC}")
    print(f"{Colors.BOLD}  Bambu Lab X1C · Mac Studio M3 Ultra{Colors.NC}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.NC}")

    # Determine target dimensions
    target_mm = DEFAULT_TARGET_MM.copy()
    if args.width:
        target_mm["width"] = args.width
    if args.height:
        target_mm["height"] = args.height
    if args.depth:
        target_mm["depth"] = args.depth

    # ── Determine starting stage ──
    if args.mesh:
        # Start from Stage 4: Mesh Repair
        mesh_path = Path(args.mesh).expanduser().resolve()
        if not mesh_path.exists():
            log_err(f"Mesh file not found: {mesh_path}")
            sys.exit(1)
        idea = mesh_path.stem
        out_dir = Path(args.output) if args.output else make_output_dir(idea)
        # Copy mesh to output dir if not already there
        if mesh_path.parent != out_dir:
            shutil.copy2(mesh_path, out_dir / "raw_mesh.obj")

        log_stage(4, "MESH REPAIR")
        t0 = time.time()
        repaired_path = repair_mesh(mesh_path, out_dir, target_mm)
        timings["mesh_repair"] = round(time.time() - t0, 1)

        print_mesh_stats(repaired_path)
        save_metadata(out_dir, idea, {}, timings)

        if not args.no_slicer:
            log_stage(5, "SLICER PREVIEW")
            open_in_slicer(repaired_path)

        return

    if args.image:
        # Start from Stage 3: Image → 3D
        image_path = Path(args.image).expanduser().resolve()
        if not image_path.exists():
            log_err(f"Image file not found: {image_path}")
            sys.exit(1)
        idea = image_path.stem
        out_dir = Path(args.output) if args.output else make_output_dir(idea)
        # Copy image to output dir
        ref_path = out_dir / "reference.png"
        if image_path != ref_path:
            shutil.copy2(image_path, ref_path)

        log_stage(3, "IMAGE → 3D MESH")
        t0 = time.time()
        mesh_path = generate_3d(image_path, out_dir)
        timings["image_to_3d"] = round(time.time() - t0, 1)

        log_stage(4, "MESH REPAIR")
        t0 = time.time()
        repaired_path = repair_mesh(mesh_path, out_dir, target_mm)
        timings["mesh_repair"] = round(time.time() - t0, 1)

        print_mesh_stats(repaired_path)
        save_metadata(out_dir, idea, {}, timings)

        if not args.no_slicer:
            log_stage(5, "SLICER PREVIEW")
            open_in_slicer(repaired_path)

        return

    # ── Full pipeline from idea ──
    idea = args.idea
    if not idea:
        print("")
        idea = input("What do you want to 3D print? → ").strip()
        if not idea:
            log_err("No idea provided. Exiting.")
            sys.exit(1)

    out_dir = Path(args.output) if args.output else make_output_dir(idea)
    log_info(f"Output directory: {out_dir}")

    # Stage 1: Idea → Prompt
    log_stage(1, "IDEA → PROMPT")
    t0 = time.time()
    prompt_data = refine_prompt(idea)
    timings["prompt_refine"] = round(time.time() - t0, 1)

    # Apply dimension overrides from prompt if user didn't specify
    if not args.width and "dimensions_mm" in prompt_data:
        suggested = prompt_data["dimensions_mm"]
        if not args.width and "width" in suggested:
            target_mm["width"] = suggested["width"]
        if not args.height and "height" in suggested:
            target_mm["height"] = suggested["height"]
        if not args.depth and "depth" in suggested:
            target_mm["depth"] = suggested["depth"]

    prompt_data = show_prompt(prompt_data, out_dir)

    # Stage 2: Prompt → Image
    log_stage(2, "PROMPT → IMAGE")
    t0 = time.time()
    image_path = generate_image(prompt_data["prompt"], out_dir)
    timings["image_gen"] = round(time.time() - t0, 1)

    show_image(image_path)

    # Stage 3: Image → 3D
    log_stage(3, "IMAGE → 3D MESH")
    t0 = time.time()
    mesh_path = generate_3d(image_path, out_dir)
    timings["image_to_3d"] = round(time.time() - t0, 1)

    # Stage 4: Mesh Repair
    log_stage(4, "MESH REPAIR")
    t0 = time.time()
    repaired_path = repair_mesh(mesh_path, out_dir, target_mm)
    timings["mesh_repair"] = round(time.time() - t0, 1)

    print_mesh_stats(repaired_path)
    save_metadata(out_dir, idea, prompt_data, timings)

    # Stage 5: Open Slicer
    if not args.no_slicer:
        log_stage(5, "SLICER PREVIEW")
        open_in_slicer(repaired_path)

    # ── Summary ──
    print(f"\n{Colors.BOLD}{'═' * 60}{Colors.NC}")
    print(f"{Colors.BOLD}  Pipeline Complete{Colors.NC}")
    print(f"{Colors.BOLD}{'═' * 60}{Colors.NC}")
    print(f"  Idea:       {idea}")
    print(f"  Output:     {out_dir}")
    total = sum(timings.values())
    print(f"  Total time: {total:.1f}s")
    for stage, t in timings.items():
        print(f"    {stage}: {t:.1f}s")
    print("")


if __name__ == "__main__":
    main()
