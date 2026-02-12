#!/usr/bin/env python3
"""package-template.py — Sanitize and package agent configs for sale.

Removes all secrets, personal data, and hardcoded paths, then packages
agent workspaces into distributable templates with documentation.

Usage:
    python3 scripts/package-template.py --agent deal-scanner --tier single
    python3 scripts/package-template.py --scan  # Scan all workspaces for publishable agents
    python3 scripts/package-template.py --agent deal-scanner,outreach-agent --tier bundle
"""

import argparse
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from textwrap import dedent

# --- Configuration ---
WORKSPACE_DIR = Path(__file__).parent.parent / "agent-configs" / "workspaces"
OPENCLAW_JSON = Path(__file__).parent.parent / "agent-configs" / "openclaw.json"
OUTPUT_DIR = Path.home() / "jarvis" / "data" / "templates" / "packages"
PRODUCT_PAGE_DIR = Path.home() / "jarvis" / "data" / "templates" / "product-pages"

# --- Sanitization patterns ---
SECRET_PATTERNS = [
    (r'\$\{[A-Z_]+TOKEN[A-Z_]*\}', 'YOUR_TOKEN_HERE'),
    (r'\$\{[A-Z_]+KEY[A-Z_]*\}', 'YOUR_API_KEY_HERE'),
    (r'\$\{[A-Z_]+SECRET[A-Z_]*\}', 'YOUR_SECRET_HERE'),
    (r'\$\{[A-Z_]+PASSWORD[A-Z_]*\}', 'YOUR_PASSWORD_HERE'),
    (r'\$\{TELEGRAM_BOT_TOKEN\}', 'YOUR_TELEGRAM_BOT_TOKEN'),
    (r'\$\{TELEGRAM_OWNER_CHAT_ID\}', 'YOUR_TELEGRAM_CHAT_ID'),
    (r'\$\{OPENCLAW_API_TOKEN\}', 'YOUR_OPENCLAW_API_TOKEN'),
]

PERSONAL_DATA_PATTERNS = [
    (r'~/jarvis/', '~/your-project/'),
    (r'/Users/[a-zA-Z0-9_]+/', '/Users/your-username/'),
    (r'/home/[a-zA-Z0-9_]+/', '/home/your-username/'),
    (r'100\.64\.\d+\.\d+', 'YOUR_TAILSCALE_IP'),
]

# --- Pricing ---
TIER_PRICING = {
    "single": {"min": 19, "max": 39, "description": "Single Agent Template"},
    "bundle": {"min": 59, "max": 99, "description": "Agent Bundle (3-5 agents)"},
    "full-stack": {"min": 149, "max": 249, "description": "Full Stack (all agents + orchestration)"},
}

AGENT_VALUE_SCORES = {
    "deal-scanner": 9,      # Direct revenue — finds acquisition targets
    "newsletter-engine": 8, # Revenue — builds subscriber base
    "outreach-agent": 8,    # Revenue — generates leads
    "reputation-monitor": 7,
    "compliance-engine": 7,
    "overnight-deliverables": 7,
    "content-studio": 6,
    "system-guardian": 5,
    "print-designer": 5,
    "argument-simulator": 7,
    "zombie-resurrector": 6,
    "codebase-archaeologist": 8,
    "template-publisher": 6,
    "microtool-factory": 8,
    "voice-hub": 7,
}


def sanitize_content(content: str) -> str:
    """Remove all secrets and personal data from content."""
    for pattern, replacement in SECRET_PATTERNS + PERSONAL_DATA_PATTERNS:
        content = re.sub(pattern, replacement, content)
    return content


def validate_sanitization(content: str, filename: str) -> list:
    """Check for remaining secrets or personal data."""
    warnings = []

    # Check for potential secrets
    secret_checks = [
        (r'[a-zA-Z0-9_]{32,}', "Possible token/key"),
        (r'sk-[a-zA-Z0-9]', "Possible OpenAI key"),
        (r'ghp_[a-zA-Z0-9]', "Possible GitHub token"),
        (r'AKIA[0-9A-Z]', "Possible AWS key"),
    ]

    for pattern, desc in secret_checks:
        if re.search(pattern, content):
            # Only warn if it's not a placeholder
            if "YOUR_" not in content[max(0, content.find(re.search(pattern, content).group()) - 20):]:
                warnings.append(f"WARNING [{filename}]: {desc} pattern detected — verify sanitization")

    return warnings


def generate_readme(agent_id: str, agents_md: str, tier: str) -> str:
    """Generate a README.md for the template package."""
    # Extract mission from AGENTS.md
    mission_match = re.search(r'## Mission\n\n(.+?)(?=\n\n##)', agents_md, re.DOTALL)
    mission = mission_match.group(1).strip() if mission_match else "AI agent configuration template."

    return dedent(f"""\
    # {agent_id.replace('-', ' ').title()} — Agent Template

    ## What This Does

    {mission}

    ## What's Included

    - `agent-config/AGENTS.md` — Complete operating instructions for the agent
    - `agent-config/SOUL.md` — Persona and communication style configuration
    - `agent-config/openclaw-snippet.json` — Drop-in configuration for OpenClaw
    - `.env.example` — All required environment variables with placeholders
    - This README with setup instructions

    ## Requirements

    - [OpenClaw](https://github.com/openclaw) agent framework (or compatible)
    - [Ollama](https://ollama.ai) running locally with the specified model
    - Environment variables configured (see `.env.example`)

    ## Quick Start

    1. Copy the `agent-config/` directory into your OpenClaw workspaces:
       ```bash
       cp -r agent-config/ /path/to/your/openclaw/workspaces/{agent_id}/
       ```

    2. Copy `.env.example` to `.env` and fill in your values:
       ```bash
       cp .env.example .env
       # Edit .env with your actual values
       ```

    3. Add the agent configuration from `openclaw-snippet.json` to your `openclaw.json`:
       ```bash
       # Merge the snippet into your agents.list[] array
       ```

    4. Pull the required Ollama model:
       ```bash
       ollama pull qwen3:30b-a3b
       ```

    5. Restart OpenClaw and test the agent.

    ## Customization

    See the inline comments in `AGENTS.md` for all configurable parameters.
    Key areas to customize:
    - Scoring thresholds and weights
    - Target domains and data sources
    - Output format and delivery targets
    - Data storage paths

    ## Support

    This is a template — it provides the configuration and instructions for building
    an AI agent. Customization to your specific use case is expected.

    ## License

    MIT — Use however you want. No warranty.
    """)


def generate_env_example(agent_config: dict) -> str:
    """Generate a .env.example file from agent config."""
    lines = [
        "# Environment variables for this agent",
        "# Copy this file to .env and fill in your values",
        "",
        "# Ollama Configuration",
        "OLLAMA_BASE_URL=http://localhost:11434",
        "",
        "# OpenClaw Gateway",
        "OPENCLAW_API_TOKEN=YOUR_OPENCLAW_API_TOKEN",
        "",
        "# Telegram Notifications (optional)",
        "TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_CHAT_ID=YOUR_TELEGRAM_CHAT_ID",
        "",
    ]

    # Add agent-specific env vars based on tools
    tools = agent_config.get("tools", [])
    if "web_search" in tools:
        lines.extend([
            "# Web Search (if using SearXNG or similar)",
            "SEARXNG_URL=http://localhost:8080",
            "",
        ])

    return "\n".join(lines)


def generate_product_page(agent_id: str, agents_md: str, tier: str) -> str:
    """Generate Gumroad-ready product page copy."""
    name = agent_id.replace("-", " ").title()

    # Calculate price
    value_score = AGENT_VALUE_SCORES.get(agent_id, 5)
    tier_info = TIER_PRICING[tier]
    price = tier_info["min"] + int((tier_info["max"] - tier_info["min"]) * (value_score / 10))

    return dedent(f"""\
    # PRODUCT PAGE — {name} Template

    **Headline**: Automate Your {name} Workflow with AI
    **Subhead**: A ready-to-deploy agent configuration that runs on your own hardware — no cloud fees, no data sharing.

    ---

    ## Description

    The {name} is a complete AI agent configuration designed for the OpenClaw framework.
    It includes detailed operating instructions, a crafted persona, and all the configuration
    needed to get a production-grade AI agent running on your local Ollama setup.

    This isn't a SaaS product with monthly fees — it's a template you own forever,
    running on your hardware, with your data staying on your machine.

    ## What's Included

    - Complete agent operating instructions (AGENTS.md)
    - Crafted persona and communication style (SOUL.md)
    - Drop-in OpenClaw configuration snippet
    - Environment variable template (.env.example)
    - Setup guide with step-by-step instructions
    - Customization documentation

    ## Requirements

    - Mac, Linux, or Windows with WSL
    - Ollama installed and running
    - 16GB+ RAM recommended (for the AI model)
    - OpenClaw framework or compatible agent runner

    ## FAQ

    **Q: Do I need an API key or subscription?**
    A: No. This runs entirely on your local machine using Ollama. No cloud API costs.

    **Q: Can I modify the agent?**
    A: Absolutely. The configuration files are plain Markdown — edit anything you want.

    **Q: What AI model does it use?**
    A: It's configured for Qwen 3 via Ollama, but you can swap in any compatible model.

    **Q: Is this a SaaS product?**
    A: No. It's a one-time purchase. You download the files and own them forever.

    ---

    **Recommended Price**: ${price}
    **Tier**: {tier_info['description']}
    """)


def scan_workspaces() -> list:
    """Scan all workspaces and assess publishability."""
    results = []

    for workspace in sorted(WORKSPACE_DIR.iterdir()):
        if not workspace.is_dir():
            continue

        agent_id = workspace.name
        agents_md = workspace / "AGENTS.md"
        soul_md = workspace / "SOUL.md"

        status = {
            "agentId": agent_id,
            "hasAgentsMd": agents_md.exists(),
            "hasSoulMd": soul_md.exists(),
            "publishable": agents_md.exists() and soul_md.exists(),
        }
        results.append(status)

    return results


def package_agent(agent_id: str, tier: str) -> str:
    """Package a single agent into a distributable template."""
    workspace = WORKSPACE_DIR / agent_id

    if not workspace.exists():
        print(f"ERROR: Workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    agents_md_path = workspace / "AGENTS.md"
    soul_md_path = workspace / "SOUL.md"

    if not agents_md_path.exists() or not soul_md_path.exists():
        print(f"ERROR: Incomplete workspace — missing AGENTS.md or SOUL.md", file=sys.stderr)
        sys.exit(1)

    # Read and sanitize
    agents_md = sanitize_content(agents_md_path.read_text())
    soul_md = sanitize_content(soul_md_path.read_text())

    # Validate sanitization
    all_warnings = []
    all_warnings.extend(validate_sanitization(agents_md, "AGENTS.md"))
    all_warnings.extend(validate_sanitization(soul_md, "SOUL.md"))

    if all_warnings:
        print("\n".join(all_warnings), file=sys.stderr)
        print("Review warnings above. Proceeding with packaging...", file=sys.stderr)

    # Build agent config snippet
    agent_config = {
        "id": agent_id,
        "name": agent_id.replace("-", " ").title(),
        "workspace": f"./workspaces/{agent_id}",
        "model": "ollama/qwen3:30b-a3b",
        "temperature": 0.5,
        "tools": ["read", "write"],
        "deliveryTargets": ["telegram"],
        "tags": [],
    }

    # Generate files
    readme = generate_readme(agent_id, agents_md, tier)
    env_example = generate_env_example(agent_config)
    product_page = generate_product_page(agent_id, agents_md, tier)

    # Create package directory
    version = "1.0"
    pkg_name = f"{agent_id}-template-v{version}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCT_PAGE_DIR.mkdir(parents=True, exist_ok=True)

    zip_path = OUTPUT_DIR / f"{pkg_name}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{pkg_name}/README.md", readme)
        zf.writestr(f"{pkg_name}/.env.example", env_example)
        zf.writestr(f"{pkg_name}/agent-config/AGENTS.md", agents_md)
        zf.writestr(f"{pkg_name}/agent-config/SOUL.md", soul_md)
        zf.writestr(f"{pkg_name}/agent-config/openclaw-snippet.json",
                     json.dumps(agent_config, indent=2))
        zf.writestr(f"{pkg_name}/CHANGELOG.md",
                     f"# Changelog\n\n## v{version} — {datetime.now().strftime('%Y-%m-%d')}\n\n- Initial release\n")

    # Save product page
    product_page_path = PRODUCT_PAGE_DIR / f"{agent_id}-product-page.md"
    product_page_path.write_text(product_page)

    print(f"Package created: {zip_path}", file=sys.stderr)
    print(f"Product page: {product_page_path}", file=sys.stderr)

    return str(zip_path)


def main():
    parser = argparse.ArgumentParser(
        description="Package OpenClaw agent configs into sellable templates"
    )
    parser.add_argument("--agent", help="Agent ID(s) to package (comma-separated)")
    parser.add_argument("--tier", choices=["single", "bundle", "full-stack"],
                        default="single", help="Pricing tier")
    parser.add_argument("--scan", action="store_true",
                        help="Scan all workspaces for publishable agents")
    args = parser.parse_args()

    if args.scan:
        results = scan_workspaces()
        print(json.dumps(results, indent=2))
        publishable = [r for r in results if r["publishable"]]
        print(f"\n{len(publishable)}/{len(results)} agents are publishable",
              file=sys.stderr)
        return

    if not args.agent:
        parser.error("Either --agent or --scan is required")

    agents = [a.strip() for a in args.agent.split(",")]

    for agent_id in agents:
        print(f"\nPackaging: {agent_id} (tier: {args.tier})", file=sys.stderr)
        package_agent(agent_id, args.tier)

    print("\nDone!", file=sys.stderr)


if __name__ == "__main__":
    main()
