#!/usr/bin/env python3
"""scaffold-microtool.py — Generate complete healthcare microtools from specs.

Creates a deployable FastAPI + Tailwind CSS application with Docker packaging
from a specification JSON file or freeform tool description.

Usage:
    python3 scripts/scaffold-microtool.py --spec specs/shift-sbar.json
    python3 scripts/scaffold-microtool.py --name ShiftSBAR --slug shift-sbar --description "Nursing shift handoff tool"
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from string import Template

# --- Configuration ---
TEMPLATE_DIR = Path(__file__).parent / "microtool-templates"
OUTPUT_BASE = Path.home() / "jarvis" / "data" / "microtools" / "builds"
SPEC_DIR = Path.home() / "jarvis" / "data" / "microtools" / "specs"


def load_template(template_name: str) -> str:
    """Load a template file from the microtool-templates directory."""
    tmpl_path = TEMPLATE_DIR / template_name
    if not tmpl_path.exists():
        print(f"WARNING: Template not found: {tmpl_path}", file=sys.stderr)
        return ""
    return tmpl_path.read_text()


def generate_models_py(spec: dict) -> str:
    """Generate Pydantic models from spec."""
    lines = [
        '"""Data models for ' + spec["name"] + '."""',
        "",
        "from datetime import datetime",
        "from typing import Optional",
        "from pydantic import BaseModel, Field",
        "",
        "",
    ]

    for model in spec.get("models", []):
        lines.append(f'class {model["name"]}(BaseModel):')
        lines.append(f'    """{model.get("description", model["name"] + " model")}."""')
        lines.append("")

        for field in model.get("fields", []):
            field_name = field["name"]
            field_type = field.get("type", "str")
            required = field.get("required", True)
            description = field.get("description", "")

            # Map types
            type_map = {
                "str": "str", "string": "str",
                "int": "int", "integer": "int",
                "float": "float",
                "bool": "bool", "boolean": "bool",
                "datetime": "datetime",
                "date": "str",  # Keep as string for simplicity
                "list": "list",
                "dict": "dict",
            }
            py_type = type_map.get(field_type, "str")

            if not required:
                py_type = f"Optional[{py_type}]"
                default = " = None"
            else:
                default = ""

            if description:
                lines.append(f'    {field_name}: {py_type}{default}  # {description}')
            else:
                lines.append(f'    {field_name}: {py_type}{default}')

        lines.append("")
        lines.append("")

    # Add audit log model
    lines.extend([
        "class AuditLogEntry(BaseModel):",
        '    """HIPAA audit log entry."""',
        "",
        "    timestamp: datetime = Field(default_factory=datetime.utcnow)",
        '    user: str = "system"',
        '    action: str  # e.g., "create", "read", "update", "delete"',
        '    resource_type: str  # e.g., "Patient", "Handoff"',
        '    resource_id: str',
        '    details: Optional[str] = None',
        "",
    ])

    return "\n".join(lines)


def generate_routes_py(spec: dict) -> str:
    """Generate FastAPI routes from spec endpoints."""
    lines = [
        '"""API routes for ' + spec["name"] + '."""',
        "",
        "from datetime import datetime",
        "from fastapi import APIRouter, HTTPException",
        "from typing import List",
        "",
        "from .models import *",
        "from .database import db",
        "",
        "router = APIRouter()",
        "",
        "",
    ]

    for endpoint in spec.get("endpoints", []):
        method = endpoint["method"].lower()
        path = endpoint["path"]
        description = endpoint.get("description", "")

        # Generate function name from path
        func_name = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        func_name = func_name.replace("-", "_")

        lines.append(f'@router.{method}("{path}")')
        lines.append(f'async def {func_name}():')
        lines.append(f'    """{description}"""')
        lines.append(f'    # TODO: Implement {description}')
        lines.append(f'    return {{"status": "ok", "message": "{description}"}}')
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def generate_main_py(spec: dict) -> str:
    """Generate the main FastAPI application file."""
    tmpl = load_template("fastapi-base/main.py.tmpl")
    if tmpl:
        return Template(tmpl).safe_substitute(
            TOOL_NAME=spec["name"],
            TOOL_SLUG=spec["slug"],
            TOOL_DESCRIPTION=spec.get("description", spec["name"]),
        )

    # Fallback if template doesn't exist
    return f'''\
"""{spec["name"]} — {spec.get("description", "Healthcare Microtool")}"""

from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .routes import router
from .database import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and clean up resources."""
    db.initialize()
    yield
    db.close()


app = FastAPI(
    title="{spec["name"]}",
    description="{spec.get("description", "")}",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api")


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """Log all requests for HIPAA audit trail."""
    start_time = datetime.utcnow()
    response = await call_next(request)
    duration = (datetime.utcnow() - start_time).total_seconds()
    db.log_audit(
        user=request.headers.get("X-User", "anonymous"),
        action=request.method,
        resource_type=request.url.path,
        resource_id="",
        details=f"status={{response.status_code}} duration={{duration:.3f}}s",
    )
    return response


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the frontend application."""
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return HTMLResponse(content=frontend_path.read_text())
    return HTMLResponse(content="<h1>{spec["name"]}</h1><p>Frontend not found.</p>")


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker."""
    return {{"status": "healthy", "timestamp": datetime.utcnow().isoformat()}}
'''


def generate_database_py(spec: dict) -> str:
    """Generate SQLite database module."""
    return f'''\
"""{spec["name"]} database — SQLite persistence with audit logging."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


class Database:
    """Simple SQLite database with HIPAA audit logging."""

    def __init__(self, db_path: str = "data/{spec["slug"]}.db"):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def initialize(self):
        """Create database and tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """Create application tables."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                user TEXT NOT NULL DEFAULT 'system',
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL DEFAULT '',
                details TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user);
        """)
        self.conn.commit()

    def log_audit(self, user: str, action: str, resource_type: str,
                  resource_id: str = "", details: str = None):
        """Write a HIPAA audit log entry. Never log PHI here."""
        self.conn.execute(
            "INSERT INTO audit_log (user, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?)",
            (user, action, resource_type, resource_id, details),
        )
        self.conn.commit()

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


# Module-level singleton
db = Database()
'''


def generate_auth_py(spec: dict) -> str:
    """Generate placeholder auth module."""
    return f'''\
"""{spec["name"]} authentication — Placeholder for hospital SSO integration."""

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic()

# --- PLACEHOLDER CREDENTIALS ---
# Replace with hospital SSO (SAML/OIDC) in production
PLACEHOLDER_USERS = {{
    "admin": "changeme",  # CHANGE THIS IMMEDIATELY
}}


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify HTTP Basic credentials. Replace with SSO in production."""
    correct_password = PLACEHOLDER_USERS.get(credentials.username)
    if correct_password is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not secrets.compare_digest(credentials.password.encode(), correct_password.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return credentials.username


# NOTE: In production, replace this entire module with:
# - SAML integration for hospital Active Directory
# - OIDC/OAuth2 for cloud-based identity providers
# - Session timeout: 15 minutes per HIPAA requirements
'''


def generate_frontend_html(spec: dict) -> str:
    """Generate the frontend HTML page."""
    tmpl = load_template("frontend-base/index.html.tmpl")
    if tmpl:
        return Template(tmpl).safe_substitute(
            TOOL_NAME=spec["name"],
            TOOL_SLUG=spec["slug"],
            TOOL_DESCRIPTION=spec.get("description", spec["name"]),
        )

    # Fallback
    return f'''\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{spec["name"]}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        /* High contrast mode for hospital environments */
        @media (prefers-contrast: high) {{
            :root {{ --bg: #000; --fg: #fff; --accent: #00ff00; }}
            body {{ background: var(--bg); color: var(--fg); }}
        }}
        /* Large touch targets for gloved hands */
        button, input, select, textarea {{
            min-height: 44px;
            min-width: 44px;
        }}
    </style>
</head>
<body class="bg-gray-50 min-h-screen">
    <nav class="bg-blue-700 text-white p-4 shadow-lg">
        <div class="max-w-4xl mx-auto flex items-center justify-between">
            <h1 class="text-xl font-bold">{spec["name"]}</h1>
            <span class="text-sm opacity-75">{spec.get("description", "")}</span>
        </div>
    </nav>

    <main class="max-w-4xl mx-auto p-4 mt-6">
        <div class="bg-white rounded-lg shadow p-6">
            <h2 class="text-lg font-semibold mb-4">Welcome to {spec["name"]}</h2>
            <p class="text-gray-600 mb-6">{spec.get("description", "Healthcare microtool")}</p>

            <div id="app" class="space-y-4">
                <p class="text-gray-400 italic">Loading...</p>
            </div>
        </div>
    </main>

    <footer class="max-w-4xl mx-auto p-4 mt-8 text-center text-xs text-gray-400">
        {spec["name"]} v1.0 | Auto-logout after 15 min inactivity | HIPAA audit logging enabled
    </footer>

    <script>
        // Session timeout — 15 minutes per HIPAA
        let inactivityTimer;
        function resetTimer() {{
            clearTimeout(inactivityTimer);
            inactivityTimer = setTimeout(() => {{
                alert("Session expired due to inactivity. Please log in again.");
                window.location.reload();
            }}, 15 * 60 * 1000);
        }}
        document.addEventListener("mousemove", resetTimer);
        document.addEventListener("keypress", resetTimer);
        resetTimer();

        // Auto-save form data to localStorage
        function autoSave(formId) {{
            const form = document.getElementById(formId);
            if (!form) return;
            const inputs = form.querySelectorAll("input, textarea, select");
            inputs.forEach(input => {{
                const key = formId + "_" + input.name;
                const saved = localStorage.getItem(key);
                if (saved) input.value = saved;
                input.addEventListener("input", () => {{
                    localStorage.setItem(key, input.value);
                }});
            }});
        }}

        // Fetch and display status
        fetch("/health")
            .then(r => r.json())
            .then(data => {{
                document.getElementById("app").innerHTML =
                    '<p class="text-green-600 font-semibold">System Online</p>' +
                    '<p class="text-gray-500 text-sm">API Status: ' + data.status + '</p>';
            }})
            .catch(() => {{
                document.getElementById("app").innerHTML =
                    '<p class="text-red-600 font-semibold">API Unreachable</p>';
            }});
    </script>
</body>
</html>'''


def generate_dockerfile(spec: dict) -> str:
    """Generate Dockerfile."""
    tmpl = load_template("Dockerfile.tmpl")
    if tmpl:
        return Template(tmpl).safe_substitute(
            TOOL_SLUG=spec["slug"],
        )

    return f'''\
FROM python:3.12-slim

# Security: run as non-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

RUN mkdir -p data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \\
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
'''


def generate_docker_compose(spec: dict) -> str:
    """Generate docker-compose.yml."""
    tmpl = load_template("docker-compose.yml.tmpl")
    if tmpl:
        return Template(tmpl).safe_substitute(
            TOOL_SLUG=spec["slug"],
            TOOL_NAME=spec["name"],
        )

    return f'''\
version: "3.8"

services:
  {spec["slug"]}:
    build: .
    container_name: {spec["slug"]}
    ports:
      - "8000:8000"
    volumes:
      - app-data:/app/data
    restart: unless-stopped
    environment:
      - TZ=America/New_York

volumes:
  app-data:
    driver: local
'''


def generate_requirements_txt() -> str:
    """Generate Python requirements."""
    return """\
fastapi==0.115.0
uvicorn[standard]==0.30.0
pydantic==2.9.0
python-multipart==0.0.9
"""


def generate_test_api_py(spec: dict) -> str:
    """Generate basic API tests."""
    return f'''\
"""Basic API tests for {spec["name"]}."""

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health_check():
    """Verify health endpoint returns 200."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_frontend_loads():
    """Verify frontend HTML is served."""
    response = client.get("/")
    assert response.status_code == 200
    assert "{spec["name"]}" in response.text
'''


def generate_hipaa_notes(spec: dict) -> str:
    """Generate HIPAA compliance documentation."""
    return f"""\
# HIPAA Compliance Notes — {spec["name"]}

## Disclaimer

This tool is a **starting point** for development, NOT a certified HIPAA-compliant application.
Before deploying with real patient data, a formal HIPAA security risk assessment is required.

## What This Tool Does

- Stores data in a local SQLite database (encrypted volume recommended)
- Logs all data access in an audit trail (timestamp, user, action)
- Implements session timeout (15 minutes of inactivity)
- Runs as a non-root user in Docker

## What This Tool Does NOT Do

- End-to-end encryption of data at rest (you must deploy on an encrypted volume)
- SAML/OIDC authentication (placeholder basic auth — replace with hospital SSO)
- Network encryption (deploy behind HTTPS reverse proxy)
- Backup and disaster recovery (implement separately)
- Business Associate Agreement (BAA) compliance (legal, not technical)

## Before Deploying with Real PHI

1. [ ] Deploy on encrypted storage volume
2. [ ] Replace placeholder auth with hospital SSO (SAML/OIDC)
3. [ ] Deploy behind HTTPS reverse proxy (nginx/caddy)
4. [ ] Configure automated encrypted backups
5. [ ] Complete HIPAA security risk assessment
6. [ ] Obtain BAA from any third-party services
7. [ ] Train users on PHI handling procedures
8. [ ] Set up audit log review process (minimum quarterly)

## Audit Log

All API requests are logged with:
- Timestamp
- User identifier (from auth header)
- HTTP method and path
- Response status code
- Request duration

**IMPORTANT**: The audit log never contains PHI (patient names, MRNs, etc.).
It logs resource IDs only, which can be cross-referenced with the database if needed.
"""


def scaffold(spec: dict):
    """Scaffold the complete microtool project."""
    slug = spec["slug"]
    output_dir = OUTPUT_BASE / slug

    print(f"Scaffolding: {spec['name']} → {output_dir}", file=sys.stderr)

    # Create directory structure
    (output_dir / "backend").mkdir(parents=True, exist_ok=True)
    (output_dir / "frontend").mkdir(parents=True, exist_ok=True)
    (output_dir / "tests").mkdir(parents=True, exist_ok=True)
    (output_dir / "data").mkdir(parents=True, exist_ok=True)

    # Generate all files
    files = {
        "backend/__init__.py": "",
        "backend/main.py": generate_main_py(spec),
        "backend/models.py": generate_models_py(spec),
        "backend/routes.py": generate_routes_py(spec),
        "backend/database.py": generate_database_py(spec),
        "backend/auth.py": generate_auth_py(spec),
        "frontend/index.html": generate_frontend_html(spec),
        "Dockerfile": generate_dockerfile(spec),
        "docker-compose.yml": generate_docker_compose(spec),
        "requirements.txt": generate_requirements_txt(),
        "tests/__init__.py": "",
        "tests/test_api.py": generate_test_api_py(spec),
        "HIPAA-NOTES.md": generate_hipaa_notes(spec),
        "README.md": generate_microtool_readme(spec),
    }

    for rel_path, content in files.items():
        filepath = output_dir / rel_path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content)
        print(f"  Created: {rel_path}", file=sys.stderr)

    # Save spec
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    spec_path = SPEC_DIR / f"{slug}-spec.json"
    spec_path.write_text(json.dumps(spec, indent=2))

    print(f"\nScaffolding complete!", file=sys.stderr)
    print(f"  Project: {output_dir}", file=sys.stderr)
    print(f"  Run: cd {output_dir} && docker compose up --build", file=sys.stderr)

    return str(output_dir)


def generate_microtool_readme(spec: dict) -> str:
    """Generate README for the microtool."""
    return f"""\
# {spec["name"]}

{spec.get("description", "Healthcare microtool")}

## Quick Start

```bash
docker compose up --build
```

Then open [http://localhost:8000](http://localhost:8000)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/` | Frontend UI |
""" + "\n".join(
    f"| {ep['method']} | `{ep['path']}` | {ep.get('description', '')} |"
    for ep in spec.get("endpoints", [])
) + """

## Development

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

## Testing

```bash
pip install pytest httpx
pytest tests/
```

## HIPAA Compliance

See [HIPAA-NOTES.md](HIPAA-NOTES.md) for compliance documentation.
This tool is a starting point — a formal security assessment is required before deploying with real PHI.
"""


def main():
    parser = argparse.ArgumentParser(
        description="Scaffold a healthcare microtool from a specification"
    )
    parser.add_argument("--spec", help="Path to spec JSON file")
    parser.add_argument("--name", help="Tool name (e.g., ShiftSBAR)")
    parser.add_argument("--slug", help="Tool slug (e.g., shift-sbar)")
    parser.add_argument("--description", help="Tool description", default="")
    args = parser.parse_args()

    if args.spec:
        spec = json.loads(Path(args.spec).read_text())
    elif args.name and args.slug:
        spec = {
            "name": args.name,
            "slug": args.slug,
            "description": args.description,
            "models": [],
            "endpoints": [],
            "features": [],
        }
    else:
        parser.error("Either --spec or --name and --slug are required")

    scaffold(spec)


if __name__ == "__main__":
    main()
