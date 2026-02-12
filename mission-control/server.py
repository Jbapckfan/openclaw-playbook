"""
Jarvis Mission Control — FastAPI + WebSocket Backend
Serves the dashboard and provides real-time system metrics.

Usage:
    cd mission-control && python3 server.py

Dependencies (all pre-installed via mac-studio-setup.sh):
    fastapi, uvicorn, httpx, psutil
"""

import asyncio
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Jarvis Mission Control", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Track connected WebSocket clients
connected_clients: list[WebSocket] = []

# Server start time for uptime tracking
SERVER_START = time.time()

DASHBOARD_PATH = Path(__file__).parent / "index.html"


# ─── Data Collectors ──────────────────────────────────────────────────────────


async def collect_system_metrics() -> dict:
    """CPU, memory, disk via psutil."""
    try:
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        load_1, load_5, load_15 = psutil.getloadavg()

        return {
            "online": True,
            "cpu": {
                "percent": cpu_percent,
                "cores": psutil.cpu_count(),
                "load": {"1m": round(load_1, 2), "5m": round(load_5, 2), "15m": round(load_15, 2)},
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 1),
                "used_gb": round(mem.used / (1024**3), 1),
                "percent": mem.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 1),
                "used_gb": round(disk.used / (1024**3), 1),
                "percent": round(disk.percent, 1),
            },
        }
    except Exception as e:
        return {"online": False, "error": str(e)}


async def collect_apple_silicon() -> dict:
    """Apple Silicon metrics via macmon (graceful fallback)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "macmon", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0 and stdout:
            data = json.loads(stdout.decode())
            return {"online": True, **data}
        return {"online": False, "error": "macmon returned no data"}
    except FileNotFoundError:
        return {"online": False, "error": "macmon not installed"}
    except asyncio.TimeoutError:
        return {"online": False, "error": "macmon timed out"}
    except Exception as e:
        return {"online": False, "error": str(e)}


async def collect_ollama_status() -> dict:
    """Ollama model list + running models via HTTP API."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            tags_resp = await client.get("http://localhost:11434/api/tags")
            tags_data = tags_resp.json() if tags_resp.status_code == 200 else {}

            ps_resp = await client.get("http://localhost:11434/api/ps")
            ps_data = ps_resp.json() if ps_resp.status_code == 200 else {}

        models = []
        for m in tags_data.get("models", []):
            models.append({
                "name": m.get("name", "unknown"),
                "size_gb": round(m.get("size", 0) / (1024**3), 1),
                "modified": m.get("modified_at", ""),
                "family": m.get("details", {}).get("family", ""),
                "parameters": m.get("details", {}).get("parameter_size", ""),
                "quantization": m.get("details", {}).get("quantization_level", ""),
            })

        running = []
        for m in ps_data.get("models", []):
            running.append({
                "name": m.get("name", "unknown"),
                "size_gb": round(m.get("size", 0) / (1024**3), 1),
                "vram_gb": round(m.get("size_vram", 0) / (1024**3), 1),
                "expires_at": m.get("expires_at", ""),
            })

        return {
            "online": True,
            "models": models,
            "running": running,
            "model_count": len(models),
            "running_count": len(running),
        }
    except httpx.ConnectError:
        return {"online": False, "error": "Ollama not reachable on port 11434"}
    except Exception as e:
        return {"online": False, "error": str(e)}


async def collect_docker_status() -> dict:
    """Docker container list + status via CLI."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "-a", "--format",
            '{"name":"{{.Names}}","status":"{{.Status}}","image":"{{.Image}}","ports":"{{.Ports}}","state":"{{.State}}"}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode != 0:
            err = stderr.decode().strip() if stderr else "docker command failed"
            return {"online": False, "error": err}

        containers = []
        for line in stdout.decode().strip().split("\n"):
            if line.strip():
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        running = sum(1 for c in containers if c.get("state") == "running")
        return {
            "online": True,
            "containers": containers,
            "total": len(containers),
            "running": running,
        }
    except FileNotFoundError:
        return {"online": False, "error": "Docker not installed"}
    except asyncio.TimeoutError:
        return {"online": False, "error": "Docker command timed out"}
    except Exception as e:
        return {"online": False, "error": str(e)}


async def collect_tailscale_status() -> dict:
    """Tailscale network status + peers."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tailscale", "status", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)

        if proc.returncode != 0 or not stdout:
            return {"online": False, "error": "tailscale status failed"}

        data = json.loads(stdout.decode())
        self_node = data.get("Self", {})
        peer_map = data.get("Peer", {})

        peers = []
        for _key, peer in peer_map.items():
            peers.append({
                "hostname": peer.get("HostName", "unknown"),
                "ip": peer.get("TailscaleIPs", [""])[0] if peer.get("TailscaleIPs") else "",
                "online": peer.get("Online", False),
                "os": peer.get("OS", ""),
                "last_seen": peer.get("LastSeen", ""),
            })

        return {
            "online": True,
            "hostname": self_node.get("HostName", ""),
            "ip": self_node.get("TailscaleIPs", [""])[0] if self_node.get("TailscaleIPs") else "",
            "peers": peers,
            "peer_count": len(peers),
            "peers_online": sum(1 for p in peers if p["online"]),
        }
    except FileNotFoundError:
        return {"online": False, "error": "Tailscale not installed"}
    except asyncio.TimeoutError:
        return {"online": False, "error": "Tailscale command timed out"}
    except Exception as e:
        return {"online": False, "error": str(e)}


async def collect_openclaw_status() -> dict:
    """OpenClaw gateway health."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:18789/health")
            if resp.status_code == 200:
                return {"online": True, **resp.json()}
            return {"online": True, "status": f"HTTP {resp.status_code}"}
    except httpx.ConnectError:
        return {"online": False, "error": "OpenClaw not reachable on port 18789"}
    except Exception as e:
        return {"online": False, "error": str(e)}


def format_uptime(seconds: float) -> str:
    """Format seconds into Xd Xh Xm string."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


# ─── HTTP Endpoints ───────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the static dashboard HTML."""
    if DASHBOARD_PATH.exists():
        return FileResponse(DASHBOARD_PATH, media_type="text/html")
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/api/health")
async def health_check():
    """Full system health check — all services."""
    system, ollama, docker, tailscale, openclaw, apple = await asyncio.gather(
        collect_system_metrics(),
        collect_ollama_status(),
        collect_docker_status(),
        collect_tailscale_status(),
        collect_openclaw_status(),
        collect_apple_silicon(),
    )
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": format_uptime(time.time() - SERVER_START),
        "system": system,
        "apple_silicon": apple,
        "ollama": ollama,
        "docker": docker,
        "tailscale": tailscale,
        "openclaw": openclaw,
    }


@app.get("/api/system")
async def system_metrics():
    """CPU, memory, disk, Apple Silicon metrics."""
    system, apple = await asyncio.gather(
        collect_system_metrics(),
        collect_apple_silicon(),
    )
    return {"system": system, "apple_silicon": apple}


@app.get("/api/ollama")
async def ollama_status():
    """Ollama model list + running models."""
    return await collect_ollama_status()


@app.get("/api/docker")
async def docker_status():
    """Docker container list + status."""
    return await collect_docker_status()


@app.get("/api/tailscale")
async def tailscale_status():
    """Tailscale network status + peers."""
    return await collect_tailscale_status()


# ─── WebSocket ────────────────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Real-time metrics push to dashboard clients."""
    await ws.accept()
    connected_clients.append(ws)
    tick = 0

    try:
        while True:
            # Every 3 seconds: lightweight metrics
            system = await collect_system_metrics()
            apple = await collect_apple_silicon()

            message = {
                "type": "metrics",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "uptime": format_uptime(time.time() - SERVER_START),
                "system": system,
                "apple_silicon": apple,
            }

            # Every 30 seconds (10 ticks): full service details
            if tick % 10 == 0:
                ollama, docker, tailscale, openclaw = await asyncio.gather(
                    collect_ollama_status(),
                    collect_docker_status(),
                    collect_tailscale_status(),
                    collect_openclaw_status(),
                )
                message["type"] = "full_update"
                message["ollama"] = ollama
                message["docker"] = docker
                message["tailscale"] = tailscale
                message["openclaw"] = openclaw

            await ws.send_json(message)
            tick += 1
            await asyncio.sleep(3)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in connected_clients:
            connected_clients.remove(ws)


# ─── Entry Point ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("\n  Jarvis Mission Control")
    print("  http://localhost:3000\n")
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="info")
