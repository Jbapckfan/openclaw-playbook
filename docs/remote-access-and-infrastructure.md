# Remote Access & Infrastructure Playbook

**For:** Mac Studio M3 Ultra Dedicated AI Server
**Author:** James Alford
**Date:** February 2026
**Research Compiled:** February 11, 2026

---

## Table of Contents

1. [Tailscale Setup on macOS for a Dedicated AI Server](#1-tailscale-setup-on-macos-for-a-dedicated-ai-server)
2. [VNC / Screen Sharing Over Tailscale](#2-vnc--screen-sharing-over-tailscale)
3. [Tailscale SSH vs VNC -- When to Use Which](#3-tailscale-ssh-vs-vnc----when-to-use-which)
4. [Tailscale Funnel & Serve for Exposing Services](#4-tailscale-funnel--serve-for-exposing-services)
5. [Tailscale ACLs to Restrict Access](#5-tailscale-acls-to-restrict-access)
6. [Webhook Endpoints via Tailscale (Not Public Internet)](#6-webhook-endpoints-via-tailscale-not-public-internet)
7. [Messaging Bots for Remote AI Commands](#7-messaging-bots-for-remote-ai-commands-imessage-telegram-signal)
8. [24/7 Headless Mac Operation](#8-247-headless-mac-operation)
9. [Web Dashboard Accessible Only via Tailscale](#9-web-dashboard-accessible-only-via-tailscale)
10. [Docker on macOS for Sandboxed AI Workloads](#10-docker-on-macos-for-sandboxed-ai-workloads)
11. [Monitoring GPU/CPU/Memory on Apple Silicon](#11-monitoring-gpucpumemory-on-apple-silicon-remotely)
12. [Backups and Disaster Recovery](#12-automatic-backups-and-disaster-recovery)

---

## 1. Tailscale Setup on macOS for a Dedicated AI Server

### Which Variant to Use

Tailscale offers [three ways to run on macOS](https://tailscale.com/kb/1065/macos-variants):

| Variant | Best For | Runs As | Survives Reboot? |
|---------|----------|---------|-----------------|
| **Mac App Store** | Personal laptops | User-space GUI app | Only if set as Login Item |
| **Standalone (download)** | General use | User-space GUI app | Only if set as Login Item |
| **CLI / Daemon (Homebrew)** | **Servers & headless machines** | System LaunchDaemon | **Yes -- starts at boot, before login** |

**For a dedicated AI server, always use the Homebrew daemon variant.** This is critical because:
- It starts at boot before any user logs in
- macOS manages the lifecycle and restarts it after sleep or crash
- It works headless with no GUI session required
- It can authenticate with pre-auth keys (no browser needed)

### Installation Steps

```bash
# Install via Homebrew
brew install tailscale

# Register as system LaunchDaemon (this is the key step)
sudo brew services start tailscale

# Verify the daemon is running
sudo brew services list | grep tailscale

# Authenticate with a pre-auth key (no browser popup)
# Generate a key at: https://login.tailscale.com/admin/settings/keys
sudo tailscale up --auth-key=tskey-auth-XXXXXXXXXXXXX

# Enable as an exit node (optional, for routing traffic)
sudo tailscale up --advertise-exit-node

# Check status
tailscale status
```

### Pre-Auth Key Setup

For a headless server, generate a **reusable, pre-authorized auth key** from the [Tailscale admin console](https://login.tailscale.com/admin/settings/keys):
- Check "Reusable" so re-authentication after updates works
- Check "Pre-authorized" so devices join without manual approval
- Set an expiry of 90 days (or use an API key for automation)
- Tag the key (e.g., `tag:ai-server`) for ACL purposes

### Ensuring Persistence

```bash
# Verify the LaunchDaemon plist exists
ls /Library/LaunchDaemons/homebrew.mxcl.tailscale.plist

# If needed, manually load it
sudo launchctl load /Library/LaunchDaemons/homebrew.mxcl.tailscale.plist

# Confirm tailscaled starts on boot
sudo launchctl list | grep tailscale
```

### Machine Name and DNS

```bash
# Set a memorable hostname for your AI server
sudo tailscale set --hostname=ai-studio

# Your server will be accessible as:
#   ai-studio.your-tailnet.ts.net
#   or via its Tailscale IP (100.x.y.z)
```

### References
- [Three ways to run Tailscale on macOS](https://tailscale.com/kb/1065/macos-variants)
- [Tailscaled on macOS (GitHub Wiki)](https://github.com/tailscale/tailscale/wiki/Tailscaled-on-macOS)
- [Self-host a local AI stack with Tailscale](https://tailscale.com/blog/self-host-a-local-ai-stack)
- [Homebrew formula for Tailscale](https://formulae.brew.sh/formula/tailscale)

---

## 2. VNC / Screen Sharing Over Tailscale

### How It Works

Tailscale makes both Macs appear on the same LAN via WireGuard-encrypted mesh networking. Each device gets a stable `100.x.y.z` IP. macOS's built-in Screen Sharing (which is a VNC server) works natively over this connection -- no port forwarding, no firewall rules, no exposure to the public internet.

### Enable Screen Sharing on the Mac Studio

```
System Settings > General > Sharing > Screen Sharing: ON
```

Configure:
- **Allow access for:** Only specific users (create a dedicated admin account)
- **Computer Settings:** Set a VNC password for non-Mac clients
- Optionally enable **Remote Management** instead (superset of Screen Sharing, adds file transfer, remote scripting, etc.)

### Connect from Another Mac

```bash
# Option 1: Use the built-in Screen Sharing app
open vnc://100.x.y.z
# or
open vnc://ai-studio.your-tailnet.ts.net

# Option 2: From Finder
# Go > Connect to Server > vnc://ai-studio.your-tailnet.ts.net

# Option 3: Use the Screens 5 app (better performance, file transfer)
# Available on Mac App Store -- supports Tailscale natively
```

### HDMI Dummy Plug (Critical for Headless)

Without a monitor connected, macOS throttles the GPU and limits VNC resolution. An HDMI dummy plug tricks macOS into thinking a display is attached:

- **Recommended:** [NewerTech HDMI Headless 4K Display Emulator](https://eshop.macsales.com/item/NewerTech/ADP4KHEAD/) (~$15)
- **Budget:** Any "HDMI Dummy Plug 4K" from Amazon ($5-10)
- Plug it into one of the Mac Studio's HDMI ports
- This enables full GPU acceleration and proper resolution for remote sessions

**Known issue (2025):** Some newer M-series Macs may cap dummy plug resolution at 1080p. If you experience this, try a different dummy plug brand or use the Thunderbolt port with a TB-to-HDMI dummy adapter.

### Security Notes

- VNC traffic over Tailscale is already encrypted end-to-end via WireGuard
- You do NOT need to wrap VNC in an SSH tunnel (this adds latency for no benefit)
- Never expose macOS Screen Sharing port (5900) to the public internet
- Use Tailscale ACLs to restrict which devices can reach port 5900

### Performance Tips

- Use **Screens 5** ($30) for better compression and adaptive quality
- Enable "Reduce motion" on the Mac Studio for smoother remote sessions
- The HDMI dummy plug dramatically improves VNC performance by keeping the GPU active

### References
- [Tailscale and RustDesk: Secure Remote Desktop Access](https://tailscale.com/blog/tailscale-rustdesk-remote-desktop-access)
- [Using Tailscale to connect via Screens](https://help.edovia.com/en/screens-5/how-to/connect-via-tailscale)
- [Headless Mode Setup for Mac Studio](https://support.astropad.com/en/articles/11835379-headless-mode-setup-how-do-i-use-a-mac-mini-or-mac-studio-without-a-monitor)

---

## 3. Tailscale SSH vs VNC -- When to Use Which

### Tailscale SSH

Tailscale SSH eliminates traditional SSH key management entirely. Instead of distributing public keys and maintaining `authorized_keys` files, Tailscale authenticates through your identity provider and authorizes access through centralized ACLs.

**Enable Tailscale SSH on the Mac Studio:**

```bash
# Enable Tailscale SSH (advertise SSH access)
sudo tailscale set --ssh

# Connect from any device on your tailnet
tailscale ssh james@ai-studio
```

**Configure SSH ACLs in your Tailscale policy:**

```jsonc
{
  "ssh": [
    {
      "action": "accept",
      "src": ["autogroup:owner"],
      "dst": ["tag:ai-server"],
      "users": ["james"]
    }
  ]
}
```

### Decision Matrix

| Task | Use SSH | Use VNC |
|------|---------|---------|
| Checking agent logs | X | |
| Restarting services | X | |
| Editing config files | X | |
| Running CLI commands | X | |
| Monitoring `htop` / `macmon` | X | |
| Git operations | X | |
| Viewing a GUI dashboard | | X |
| Debugging a stuck GUI app | | X |
| Initial macOS setup | | X |
| Granting macOS permissions dialogs | | X |
| Viewing ComfyUI / Dyad output | | X |
| Running Apple Shortcuts | | X |
| Approving macOS security prompts | | X |

### Recommendation for AI Server Management

**Use SSH for 90% of daily operations:**
- Starting/stopping Ollama, OpenClaw, ComfyUI
- Tailing logs (`tail -f ~/.openclaw/logs/agent.log`)
- Checking GPU utilization (`macmon` or `asitop`)
- Running scripts and deployments
- Lower bandwidth, faster response, works on poor connections

**Use VNC for the other 10%:**
- Initial system setup and macOS permission grants
- GUI-only applications
- Debugging display-related issues
- When you need to see what's on the screen

### Tailscale SSH Bonus Features

- **Web-based SSH console:** Access from any browser via the Tailscale admin panel
- **Session recording:** Enable for audit trails on production commands
- **Automatic key rotation:** No stale SSH keys to manage
- **Check mode:** Require re-authentication for sensitive operations

### References
- [Tailscale SSH: Manage SSH Keys Securely](https://tailscale.com/tailscale-ssh)
- [Tailscale SSH Blog Post](https://tailscale.com/blog/tailscale-ssh)
- [Setup Tailscale CLI with SSH on macOS](https://gist.github.com/skylarbpayne/5ee9604dff0631d1b3f2357e62db7dba)
- [Tailscale Web-Based SSH Console](https://tailscale.com/blog/tailscale-web-ssh-console)

---

## 4. Tailscale Funnel & Serve for Exposing Services

### Tailscale Serve (Tailnet-Only)

`tailscale serve` exposes a local service to your tailnet only -- accessible from any device on your Tailscale network, but invisible to the public internet.

```bash
# Expose a local web service to your tailnet
tailscale serve 8080
# Now accessible at: https://ai-studio.your-tailnet.ts.net/

# Expose on a specific HTTPS port
tailscale serve --https=443 8080

# Serve a specific path
tailscale serve --set-path=/dashboard 3000

# Serve a local directory (great for file sharing)
tailscale serve /path/to/files

# Run in background
tailscale serve --bg 8080

# List active serves
tailscale serve status

# Stop serving
tailscale serve off
```

**Use cases for your AI server:**
- Expose OpenClaw web dashboard: `tailscale serve 18789`
- Expose ComfyUI: `tailscale serve --set-path=/comfyui 8188`
- Expose Grafana monitoring: `tailscale serve --set-path=/monitoring 3000`
- Expose SearXNG: `tailscale serve --set-path=/search 8888`

### Tailscale Funnel (Public Internet)

`tailscale funnel` exposes a local service to the entire internet via a Tailscale-provided domain. This is **double opt-in**: it must be enabled in the admin console AND on the device.

```bash
# Enable Funnel in admin console first, then:
tailscale funnel 3000
# Now accessible at: https://ai-studio.your-tailnet.ts.net/ (from anywhere)

# Funnel with background mode
tailscale funnel --bg 3000

# Stop funneling
tailscale funnel off
```

**When to use Funnel:**
- Receiving webhooks from GitHub, Telegram, Stripe
- Sharing a demo URL with a client
- Public-facing API endpoints

**When NOT to use Funnel:**
- Internal dashboards (use `serve` instead)
- Anything with sensitive data
- Services that should only be accessible by you

### Named Services (Advanced)

```bash
# Expose a service with its own DNS name on your tailnet
tailscale serve --service="svc:ai-dashboard" --tcp 443 localhost:18789
# Accessible as: https://ai-dashboard.your-tailnet.ts.net

tailscale serve --service="svc:ollama-api" --tcp 443 localhost:11434
# Accessible as: https://ollama-api.your-tailnet.ts.net
```

### References
- [Reintroducing Serve and Funnel](https://tailscale.com/blog/reintroducing-serve-funnel)
- [Tailscale Funnel: Securely Expose Local Services](https://tailscale.com/blog/introducing-tailscale-funnel)
- [How to Use Tailscale Funnel (2025 Guide)](https://subnetsavy.com/wp-content/uploads/articles/tailscale-funnel-guide.html)
- [Four ways to put a service on your tailnet](https://tailscale.com/blog/four-ways-tailscale-service)

---

## 5. Tailscale ACLs to Restrict Access

### Basic Concepts

Tailscale ACLs (Access Control Lists) define who can connect to what on your network. By default, all devices on your tailnet can talk to each other. ACLs let you lock this down.

### Recommended ACL Configuration for AI Server

Edit your policy at [https://login.tailscale.com/admin/acls](https://login.tailscale.com/admin/acls):

```jsonc
{
  // Define groups
  "groups": {
    "group:admin": ["james@gmail.com"],
    "group:family": ["partner@gmail.com", "kid@gmail.com"]
  },

  // Define tags for device categories
  "tagOwners": {
    "tag:ai-server": ["group:admin"],
    "tag:monitoring": ["group:admin"],
    "tag:personal": ["group:admin"]
  },

  // Access rules (using the newer "grants" syntax)
  "grants": [
    {
      // Admin has full access to everything
      "src": ["group:admin"],
      "dst": ["*:*"],
      "ip": ["*:*"]
    },
    {
      // Family can access the web dashboard only (port 443 via Tailscale Serve)
      "src": ["group:family"],
      "dst": ["tag:ai-server"],
      "ip": ["tcp:443"]
    },
    {
      // Block family from SSH
      "src": ["group:family"],
      "dst": ["tag:ai-server"],
      "ip": ["!tcp:22"]
    }
  ],

  // SSH-specific rules
  "ssh": [
    {
      "action": "accept",
      "src": ["group:admin"],
      "dst": ["tag:ai-server"],
      "users": ["james"]
    },
    {
      // Deny SSH from all other sources
      "action": "reject",
      "src": ["*"],
      "dst": ["tag:ai-server"],
      "users": ["*"]
    }
  ]
}
```

### Applying Tags to Your Mac Studio

```bash
# Tag your Mac Studio as the AI server
# Do this in the Tailscale admin console: Machines > ai-studio > Edit ACL tags
# Add tag: tag:ai-server
```

Or via the CLI:
```bash
sudo tailscale up --advertise-tags=tag:ai-server
```

### Device Posture (Advanced)

Tailscale supports [Device Posture management](https://tailscale.com/blog/device-posture), letting you restrict access based on:
- OS version (require macOS 15+)
- Disk encryption status (require FileVault)
- Screen lock enabled
- Device identity

### Port-Level Granularity

```jsonc
{
  "grants": [
    {
      "src": ["group:admin"],
      "dst": ["tag:ai-server"],
      "ip": [
        "tcp:22",     // SSH
        "tcp:443",    // HTTPS (Tailscale Serve)
        "tcp:5900",   // VNC
        "tcp:8080",   // Web dashboard
        "tcp:11434",  // Ollama API
        "tcp:18789"   // OpenClaw
      ]
    }
  ]
}
```

### References
- [Tailscale ACL Tags (GA)](https://tailscale.com/blog/acl-tags-ga)
- [Tailscale Grants (GA)](https://tailscale.com/blog/grants-ga)
- [Managing Tailscale Network Access with ACLs](https://medium.com/@blabber_ducky/managing-tailscale-network-access-with-acls-e2989b550e27)
- [Device Posture Management](https://tailscale.com/blog/device-posture)

---

## 6. Webhook Endpoints via Tailscale (Not Public Internet)

### The Problem

External services (GitHub, Telegram, Stripe) need to send webhooks to your AI server, but your server is only accessible via Tailscale (by design). Tailscale's internal IPs (100.x.y.z and *.ts.net) are not routable from the public internet.

### Solution 1: Tailscale Funnel (Simplest)

Use Funnel to selectively expose only the webhook endpoint:

```bash
# Expose just the webhook listener
tailscale funnel --bg 8080
# External services can now reach: https://ai-studio.your-tailnet.ts.net:443
```

Your webhook handler only listens on a specific path (e.g., `/webhook/telegram`) and validates signatures. Everything else on the machine stays private.

### Solution 2: Tailgator (Purpose-Built)

[Tailgator](https://tailgator.app/) is a serverless reverse proxy designed specifically for this problem:

- Provides a stable public URL for each webhook endpoint
- Tunnels traffic over Tailscale to your private service
- No inbound ports to open on your network
- Dashboard-managed routing rules
- Webhook bodies stream through encrypted tunnels in-memory (never persisted)
- Free during preview period (as of early 2026)

### Solution 3: Lightweight Relay on a VPS

Deploy a tiny relay on a $5/month VPS (Fly.io, Railway, etc.):

```
Internet --> VPS (public IP) --> Tailscale --> Mac Studio (private)
```

```bash
# On the VPS, install Tailscale and Nginx
# Nginx config proxies webhook requests to the Mac Studio's Tailscale IP

# /etc/nginx/sites-available/webhook-relay
server {
    listen 443 ssl;
    server_name webhooks.yourdomain.com;

    location /webhook/ {
        proxy_pass http://100.x.y.z:8080/webhook/;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Solution 4: AWS Lambda Webhook Forwarder

For production-grade setups, AWS published a pattern using a [Lambda extension with Tailscale](https://aws.amazon.com/blogs/compute/building-a-secure-webhook-forwarder-using-an-aws-lambda-extension-and-tailscale/):

- Lambda receives the webhook on a public HTTPS endpoint
- A custom Lambda extension establishes a WireGuard tunnel to your tailnet
- The Lambda function proxies the request to your Mac Studio over the tunnel

### Recommended Approach for Your Setup

**Use Tailscale Funnel** for simplicity. It is:
- Zero additional infrastructure
- End-to-end encrypted
- ACL-controlled
- Free

Pair it with webhook signature validation in your application:

```python
# Example: Validate Telegram webhook
import hmac
import hashlib

def verify_telegram_webhook(token, data, received_hash):
    secret = hashlib.sha256(token.encode()).digest()
    computed = hmac.new(secret, data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, received_hash)
```

### References
- [Tailgator: Serverless Reverse Proxy for Tailscale](https://tailgator.app/)
- [AWS Lambda Webhook Forwarder with Tailscale](https://aws.amazon.com/blogs/compute/building-a-secure-webhook-forwarder-using-an-aws-lambda-extension-and-tailscale/)
- [Develop Webhooks Locally Using Tailscale Funnel (Twilio)](https://www.twilio.com/en-us/blog/developers/tutorials/develop-webhooks-locally-using-tailscale-funnel)
- [Tailscale Webhooks Design](https://tailscale.com/blog/webhooks-design)

---

## 7. Messaging Bots for Remote AI Commands (iMessage, Telegram, Signal)

### Overview

The goal: text your AI server a command from your phone and get results back. Three main channels, each with different tradeoffs.

### iMessage (macOS-Native, Best for Apple Ecosystem)

**Why iMessage:** Zero additional accounts needed, end-to-end encrypted by Apple, works from every Apple device you own, family members can use it naturally.

**Option A: OpenClaw iMessage Integration**

[OpenClaw](https://docs.openclaw.ai/channels/imessage) has built-in iMessage support via the `imsg` CLI:

```bash
# OpenClaw's iMessage channel works via a local CLI integration (macOS only)
# First-run requires granting:
#   - Automation permission (System Settings > Privacy > Automation)
#   - Full Disk Access (for reading Messages database)
openclaw config set channel imessage
```

**Option B: imsg CLI (Standalone)**

[imsg](https://github.com/steipete/imsg) is a CLI for Messages.app that lets agents send and receive iMessages:

```bash
# Install
brew install steipete/tap/imsg

# Send a message
imsg send "+1234567890" "GPU at 78%, all agents healthy"

# Watch for new messages (event-driven via filesystem events)
imsg watch --from "+1234567890" --json

# Read recent messages
imsg read --from "+1234567890" --limit 10 --json
```

**Option C: AppleScript (Low-Level)**

```applescript
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "+1234567890" of targetService
    send "Agent report: all systems nominal" to targetBuddy
end tell
```

**Permissions Required:**
- Automation permission for Messages.app
- Full Disk Access (to read `~/Library/Messages/chat.db`)
- First-time GUI approval on the Mac

### Telegram (Most Flexible, Cross-Platform)

**Why Telegram:** Works on any device, rich formatting (markdown, buttons, inline keyboards), file/image sharing, bot API is excellent, webhook support.

**Setup Steps:**

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Save the API token (treat like a password)
3. Run a Python bot on your Mac Studio

```python
# requirements: python-telegram-bot>=21.0
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

BOT_TOKEN = "your-bot-token"

async def start(update: Update, context):
    await update.message.reply_text("AI Server Online. Commands:\n/status - System status\n/gpu - GPU usage\n/run <command> - Execute command")

async def status(update: Update, context):
    import subprocess
    result = subprocess.run(["macmon", "--json"], capture_output=True, text=True)
    await update.message.reply_text(f"```\n{result.stdout}\n```", parse_mode="Markdown")

async def run_command(update: Update, context):
    cmd = " ".join(context.args)
    # SECURITY: Whitelist allowed commands
    allowed = ["macmon", "tailscale status", "ollama list", "docker ps"]
    if not any(cmd.startswith(a) for a in allowed):
        await update.message.reply_text("Command not in allowlist")
        return
    result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=30)
    await update.message.reply_text(f"```\n{result.stdout[:4000]}\n```", parse_mode="Markdown")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("run", run_command))
app.run_polling()
```

**Webhook mode (production):** Use Tailscale Funnel to receive Telegram webhooks:
```bash
tailscale funnel --bg 8443
# Set webhook URL: https://ai-studio.your-tailnet.ts.net/telegram-webhook
```

### Signal (Most Private)

**Why Signal:** Strongest privacy guarantees, no phone number exposure to a third-party bot platform, self-hosted.

**Setup with signal-cli:**

```bash
# Install signal-cli
brew install signal-cli

# Register with a spare phone number
signal-cli -u +1XXXXXXXXXX register
signal-cli -u +1XXXXXXXXXX verify CODE

# Send a message
signal-cli -u +1XXXXXXXXXX send -m "Agent status: OK" +1YYYYYYYYYY

# Receive messages (daemon mode)
signal-cli -u +1XXXXXXXXXX daemon --json
```

**For a bot framework, use [signalbot](https://pypi.org/project/signalbot/):**

```bash
pip install signalbot

# Run signal-cli-rest-api in Docker
docker run -d --name signal-api -p 8080:8080 \
  -v signal-data:/home/.local/share/signal-cli \
  bbernhard/signal-cli-rest-api
```

### Recommendation

| Channel | Privacy | Ease of Setup | Rich Media | Cross-Platform | Best For |
|---------|---------|--------------|------------|---------------|----------|
| **iMessage** | High (E2E) | Medium (macOS perms) | Limited | Apple only | Personal/family use |
| **Telegram** | Medium | Easy (BotFather) | Excellent | All platforms | Daily AI interaction |
| **Signal** | Highest | Hard (signal-cli) | Basic | All platforms | Maximum privacy |

**For your setup:** Use Telegram as primary (best bot API, rich formatting, inline keyboards for interactive commands) and iMessage as secondary (for family members who will never install Telegram).

### References
- [OpenClaw iMessage Integration](https://docs.openclaw.ai/channels/imessage)
- [imsg CLI for Messages.app](https://github.com/steipete/imsg)
- [Jared: iMessage Chat Bot](https://github.com/ZekeSnider/Jared)
- [python-telegram-bot Library](https://github.com/python-telegram-bot/python-telegram-bot)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [signal-cli](https://github.com/AsamK/signal-cli)
- [signal-cli-rest-api (Docker)](https://github.com/bbernhard/signal-cli-rest-api)
- [signalbot Python Package](https://pypi.org/project/signalbot/)

---

## 8. 24/7 Headless Mac Operation

### Power Management Settings

```bash
# Prevent sleep entirely
sudo pmset -a sleep 0              # Never sleep
sudo pmset -a disksleep 0          # Never spin down disks
sudo pmset -a displaysleep 0       # Never turn off display (or set to 1 min if dummy plug)

# Auto-restart after power failure
sudo pmset -a autorestart 1

# Wake on network access (Wake-on-LAN)
sudo pmset -a womp 1

# Keep awake when any SSH/remote session is active
sudo pmset -a ttyskeepawake 1

# Disable Power Nap (prevents random wake/sleep cycles)
sudo pmset -a powernap 0

# Verify all settings
pmset -g custom
```

### GUI Settings (System Settings)

```
System Settings > Energy:
  - "Prevent automatic sleeping when the display is off": ON
  - "Wake for network access": ON
  - "Start up automatically after a power failure": ON

System Settings > Lock Screen:
  - "Start Screen Saver when inactive": Never
  - "Turn display off on battery/power adapter": Never (or 1 minute)
```

### HDMI Dummy Plug

As mentioned in the VNC section, a $5-15 HDMI dummy plug is essential:
- Forces GPU to stay active
- Provides proper resolution for remote desktop
- Prevents macOS from throttling graphics

### Scheduled Maintenance Restarts

```bash
# Schedule a weekly restart at 4 AM Sunday
sudo pmset repeat wakeorpoweron MTWRFSU 03:55:00
# Then use a launchd job or cron to restart at 4 AM:
# sudo shutdown -r now

# Alternative: Use a cron job
sudo crontab -e
# Add: 0 4 * * 0 /sbin/shutdown -r now
```

### Caffeinate for Long-Running Tasks

```bash
# Prevent sleep while a specific process runs
caffeinate -i -w $(pgrep ollama)

# Prevent sleep for a specific duration (8 hours)
caffeinate -i -t 28800 &

# Prevent sleep while a command runs
caffeinate -i -- python long_training_job.py
```

### Automatic Login (Optional but Useful)

For GUI apps that need a user session:
```
System Settings > Users & Groups > Login Options:
  - Automatic login: [your user]
```

**Security note:** Only do this if the Mac is physically secure AND you rely on Tailscale ACLs for remote access control.

### Monitoring Uptime and Health

Create a simple health check script:

```bash
#!/bin/bash
# /usr/local/bin/health-check.sh

UPTIME=$(uptime)
MEMORY=$(memory_pressure | head -5)
DISK=$(df -h / | tail -1)
TAILSCALE=$(tailscale status --json | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['Online'])")

echo "=== AI Server Health ==="
echo "Uptime: $UPTIME"
echo "Memory: $MEMORY"
echo "Disk: $DISK"
echo "Tailscale: $TAILSCALE"
```

### LaunchDaemon for Auto-Starting Services

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ai.ollama</string>
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
    <string>/var/log/ollama.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/ollama-error.log</string>
</dict>
</plist>
```

Save as `/Library/LaunchDaemons/com.ai.ollama.plist` and load with:
```bash
sudo launchctl load /Library/LaunchDaemons/com.ai.ollama.plist
```

### References
- [How I Turned My Mac Into a Headless Server (Medium)](https://chawlaharshit.medium.com/how-i-turned-my-mac-into-a-headless-server-my-always-on-setup-for-ai-monitoring-and-automation-aa9a8ff9aeff)
- [Mac Mini M4 AI Server Setup (2026)](https://www.marc0.dev/en/blog/mac-mini-ai-server-ollama-openclaw-claude-code-complete-guide-2026-1770481256372)
- [Setting Up a Mac as a Headless Server (JT Bullitt)](https://www.jtbullitt.com/tech/mac/mac-standalone.html)
- [pmset Reference](https://www.dssw.co.uk/reference/pmset/)
- [Best Guide: Mac Mini as Server (2026)](https://reviewandbuytech.com/best-guide-mac-mini-as-server-2026/)

---

## 9. Web Dashboard Accessible Only via Tailscale

### Option A: Homepage (gethomepage.dev) -- Recommended

[Homepage](https://gethomepage.dev/) is a modern, self-hosted dashboard for monitoring all your services. It has native Tailscale widget support.

```bash
# Install via Docker
docker run -d \
  --name homepage \
  -p 3000:3000 \
  -v /path/to/config:/app/config \
  ghcr.io/gethomepage/homepage:latest

# Expose only via Tailscale Serve (not the public internet)
tailscale serve --bg 3000
# Accessible at: https://ai-studio.your-tailnet.ts.net/
```

**Configure `services.yaml`:**
```yaml
- AI Services:
    - Ollama:
        href: http://localhost:11434
        description: Local LLM inference
        icon: ollama.png
        widget:
          type: customapi
          url: http://localhost:11434/api/tags
    - OpenClaw:
        href: http://localhost:18789
        description: AI Agent Command Center
        icon: mdi-robot
    - ComfyUI:
        href: http://localhost:8188
        description: Image generation pipeline
        icon: mdi-image-auto-adjust
    - SearXNG:
        href: http://localhost:8888
        description: Private search engine
        icon: searxng.png

- Monitoring:
    - Grafana:
        href: http://localhost:3001
        description: System metrics
        icon: grafana.png
    - Tailscale:
        description: Network status
        widget:
          type: tailscale
          deviceid: your-device-id
          key: tskey-api-XXXXX

- Infrastructure:
    - Docker:
        description: Container status
        widget:
          type: docker
          server: local
```

### Option B: Home Assistant (For Home Automation Integration)

If you want to combine AI server monitoring with home automation:

```bash
# Install Home Assistant Container
docker run -d \
  --name homeassistant \
  -p 8123:8123 \
  -v /path/to/config:/config \
  ghcr.io/home-assistant/home-assistant:stable

# Expose via Tailscale Serve
tailscale serve --set-path=/ha --bg 8123
```

Home Assistant has a [native Tailscale integration](https://www.home-assistant.io/integrations/tailscale/) for monitoring your tailnet devices.

### Option C: Dashy (Highly Customizable)

```bash
docker run -d \
  --name dashy \
  -p 4000:8080 \
  -v /path/to/conf.yml:/app/user-data/conf.yml \
  lissy93/dashy:latest

tailscale serve --set-path=/dash --bg 4000
```

### Securing with Tailscale Serve

The key security property: when you use `tailscale serve`, the service is ONLY accessible from devices on your tailnet. There is no public URL. Combined with ACLs, you can further restrict which tailnet devices can access it.

```bash
# Verify the service is tailnet-only
curl https://ai-studio.your-tailnet.ts.net/  # Works from tailnet device
curl https://ai-studio.your-tailnet.ts.net/  # Fails from non-tailnet device
```

### References
- [Homepage Dashboard](https://gethomepage.dev/)
- [Homepage Tailscale Widget](https://gethomepage.dev/widgets/services/tailscale/)
- [Home Assistant Tailscale Integration](https://www.home-assistant.io/integrations/tailscale/)
- [Access Home Assistant Remotely with Tailscale](https://tailscale.com/blog/remotely-access-home-assistant)
- [I use Tailscale to remotely access my self-hosted services (XDA)](https://www.xda-developers.com/tailscale-guide/)

---

## 10. Docker on macOS for Sandboxed AI Workloads

### Current State (Early 2026)

Running containers on macOS Apple Silicon has several options, each with tradeoffs:

| Runtime | GPU Access | Performance | Ease of Use | Native macOS |
|---------|-----------|-------------|-------------|-------------|
| **Docker Desktop** | Via Model Runner only | Good (LinuxKit VM) | Best | No (VM) |
| **OrbStack** | No GPU in containers | Great (optimized VM) | Great | No (VM) |
| **Podman + libkrun** | Vulkan (via Metal) | Good | Medium | No (VM) |
| **Apple Container** (macOS 26) | TBD | Excellent (native) | Early-stage | **Yes** |
| **Native (no container)** | **Full Metal/ANE** | **Best** | Varies | **Yes** |

### Docker Desktop Setup

```bash
# Install Docker Desktop for Apple Silicon
brew install --cask docker

# Or use OrbStack (lighter weight, recommended)
brew install --cask orbstack
```

### Docker Model Runner (GPU-Accelerated AI)

Docker Model Runner runs AI models directly on the host (not in a VM), giving full Metal GPU acceleration on Apple Silicon:

```bash
# Enable Model Runner in Docker Desktop settings
# Then pull and run models:
docker model pull llama3.2
docker model run llama3.2 "Explain quantum computing"

# Expose model as an OpenAI-compatible API
docker model serve llama3.2 --port 8080
```

### Sandboxed AI Agent Workloads

For running AI agents in isolated environments:

```bash
# Docker sandbox for Claude Code (official Docker sandbox)
docker run -it --rm \
  -v /path/to/workspace:/workspace \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  docker.io/anthropic/claude-code-sandbox:latest

# Custom sandbox for your agents
docker run -d \
  --name agent-sandbox \
  --memory=8g \
  --cpus=4 \
  --network=bridge \
  -v /shared/data:/data:ro \
  your-agent-image:latest
```

### Docker Compose for AI Stack

```yaml
# docker-compose.yml
version: "3.9"
services:
  searxng:
    image: searxng/searxng:latest
    ports:
      - "8888:8080"
    volumes:
      - ./searxng:/etc/searxng

  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8000:8000"
    volumes:
      - chroma-data:/chroma/chroma

  homepage:
    image: ghcr.io/gethomepage/homepage:latest
    ports:
      - "3000:3000"
    volumes:
      - ./homepage:/app/config

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3001:3000"
    volumes:
      - grafana-data:/var/lib/grafana

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

volumes:
  chroma-data:
  grafana-data:
```

### Apple Container (macOS 26 Tahoe -- Coming)

Apple announced a [native container runtime](https://github.com/apple/container) at WWDC 2025:
- Each container runs in its own lightweight micro-VM with isolated Linux kernel
- Written in Swift, optimized for Apple Silicon
- OCI-compliant (pulls standard Docker images)
- Requires macOS 26 Tahoe

```bash
# When available:
container pull docker.io/library/ubuntu:latest
container run ubuntu:latest -- /bin/bash
```

This will be the future-preferred option for macOS servers, but as of early 2026 it is still in early stages.

### Key Recommendation

**For AI inference: run Ollama and MLX models natively (not in Docker).** They need direct Metal GPU access. Use Docker for supporting services (databases, web servers, monitoring tools, search engines) that do not need GPU acceleration.

### References
- [Docker Sandboxes for Claude Code](https://www.docker.com/blog/docker-sandboxes-run-claude-code-and-other-coding-agents-unsupervised-but-safely/)
- [Docker Model Runner](https://www.docker.com/blog/introducing-docker-model-runner/)
- [How to Sandbox AI Agents in 2026 (Northflank)](https://northflank.com/blog/how-to-sandbox-ai-agents)
- [Apple Container (GitHub)](https://github.com/apple/container)
- [Apple Containers vs Docker (The New Stack)](https://thenewstack.io/apple-containers-on-macos-a-technical-comparison-with-docker/)
- [GPU-Accelerated Containers for M-series Macs](https://medium.com/@andreask_75652/gpu-accelerated-containers-for-m1-m2-m3-macs-237556e5fe0b)
- [Podman AI Inference on macOS (Red Hat)](https://developers.redhat.com/articles/2025/06/05/how-we-improved-ai-inference-macos-podman-containers)

---

## 11. Monitoring GPU/CPU/Memory on Apple Silicon Remotely

### Tool Comparison

| Tool | Sudo Required | GPU Metrics | Export | Language | Install |
|------|:------------:|:-----------:|--------|----------|---------|
| **macmon** | No | Yes | JSON | Rust | `brew install vladkens/tap/macmon` |
| **asitop** | Yes | Yes | Terminal | Python | `pip install asitop` |
| **mactop** | Yes | Yes | Terminal | Go | `brew install mactop` |
| **fluidtop** | Yes | Yes | Terminal | Python | Fork of asitop |
| **powermetrics** | Yes | Yes | plist/JSON | Built-in | Pre-installed |

### macmon (Recommended -- Sudoless)

[macmon](https://github.com/vladkens/macmon) is the best choice for remote/automated monitoring:

```bash
# Install
brew install vladkens/tap/macmon

# Interactive TUI mode
macmon

# JSON output (perfect for Prometheus/Grafana)
macmon --json

# Sample output:
# {
#   "cpu_usage": 12.5,
#   "gpu_usage": 45.2,
#   "memory_used": 48.3,
#   "memory_total": 192.0,
#   "cpu_power": 8.2,
#   "gpu_power": 22.1,
#   "cpu_temp": 42.0,
#   "gpu_temp": 45.0
# }
```

### Prometheus + Grafana Stack

```bash
# 1. Create a simple exporter script that wraps macmon
cat > /usr/local/bin/macmon-exporter.py << 'EOF'
#!/usr/bin/env python3
import subprocess, json, time
from http.server import HTTPServer, BaseHTTPRequestHandler

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return

        result = subprocess.run(["macmon", "--json"], capture_output=True, text=True)
        data = json.loads(result.stdout)

        metrics = []
        metrics.append(f'apple_silicon_cpu_usage {data["cpu_usage"]}')
        metrics.append(f'apple_silicon_gpu_usage {data["gpu_usage"]}')
        metrics.append(f'apple_silicon_memory_used_gb {data["memory_used"]}')
        metrics.append(f'apple_silicon_memory_total_gb {data["memory_total"]}')
        metrics.append(f'apple_silicon_cpu_power_watts {data["cpu_power"]}')
        metrics.append(f'apple_silicon_gpu_power_watts {data["gpu_power"]}')
        metrics.append(f'apple_silicon_cpu_temp_celsius {data["cpu_temp"]}')
        metrics.append(f'apple_silicon_gpu_temp_celsius {data["gpu_temp"]}')

        body = "\n".join(metrics)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body.encode())

HTTPServer(("0.0.0.0", 9101), MetricsHandler).serve_forever()
EOF

chmod +x /usr/local/bin/macmon-exporter.py

# 2. Add to prometheus.yml
# scrape_configs:
#   - job_name: 'apple_silicon'
#     static_configs:
#       - targets: ['localhost:9101']
#     scrape_interval: 10s
```

### Grafana Dashboard

A pre-built [Grafana dashboard for macOS](https://grafana.com/grafana/dashboards/18302-macos-gpu/) is available that displays:
- CPU and GPU utilization over time
- Memory pressure and swap usage
- Power consumption (watts)
- Temperature trends
- ANE (Neural Engine) utilization

### Remote Monitoring via Telegram

Combine with the Telegram bot from Section 7:

```python
# Add to your Telegram bot
async def gpu_status(update: Update, context):
    result = subprocess.run(["macmon", "--json"], capture_output=True, text=True)
    data = json.loads(result.stdout)
    msg = (
        f"GPU: {data['gpu_usage']:.1f}% ({data['gpu_power']:.1f}W)\n"
        f"CPU: {data['cpu_usage']:.1f}% ({data['cpu_power']:.1f}W)\n"
        f"RAM: {data['memory_used']:.1f}/{data['memory_total']:.0f} GB\n"
        f"Temp: CPU {data['cpu_temp']:.0f}C / GPU {data['gpu_temp']:.0f}C"
    )
    await update.message.reply_text(f"```\n{msg}\n```", parse_mode="Markdown")
```

### Built-in macOS Tools

```bash
# powermetrics (built-in, requires sudo)
sudo powermetrics --samplers gpu_power,cpu_power -i 1000 -n 1

# Activity Monitor via CLI
top -l 1 -s 0 | head -20

# Memory pressure
memory_pressure

# Disk I/O
iostat -w 1 -c 5
```

### References
- [macmon: Sudoless Apple Silicon Monitor](https://github.com/vladkens/macmon)
- [asitop: Performance Monitoring for Apple Silicon](https://github.com/tlkh/asitop)
- [mactop: Apple Silicon Monitor Top](https://github.com/metaspartan/mactop)
- [fluidtop: Enhanced asitop Fork](https://github.com/FluidInference/fluidtop)
- [Grafana macOS GPU Dashboard](https://grafana.com/grafana/dashboards/18302-macos-gpu/)
- [Monitor Apple Silicon with macmon + Hosted Graphite](https://www.metricfire.com/blog/monitor-apple-silicon-gpu-on-macos-with-macmon-hosted-graphite/)

---

## 12. Automatic Backups and Disaster Recovery

### 3-2-1 Backup Strategy

Keep **3** copies of your data, on **2** different media, with **1** offsite:

1. **Local:** Time Machine to external SSD
2. **Local 2:** Restic/Borg to NAS or second drive
3. **Offsite:** Restic to cloud (Backblaze B2, rsync.net, BorgBase)

### Time Machine (Simplest, for Full System)

```bash
# Enable Time Machine via CLI
sudo tmutil enable

# Set backup destination (external drive)
sudo tmutil setdestination /Volumes/BackupDrive

# For NAS backup (use SMB, not AFP -- AFP is deprecated)
sudo tmutil setdestination smb://user:password@nas.local/TimeMachine

# Exclude large model files from Time Machine (back these up separately)
sudo tmutil addexclusion ~/.ollama/models
sudo tmutil addexclusion ~/ComfyUI/models
sudo tmutil addexclusion ~/models

# Verify exclusions
tmutil isexcluded ~/.ollama/models
```

### Restic (Recommended for Automated, Encrypted, Incremental)

[Restic](https://restic.net/) is the best tool for automated server backups:

```bash
# Install
brew install restic

# Initialize a repository on Backblaze B2
export B2_ACCOUNT_ID="your-account-id"
export B2_ACCOUNT_KEY="your-account-key"
restic -r b2:your-bucket:ai-server init

# First backup
restic -r b2:your-bucket:ai-server backup \
  /Users/james/openclaw-playbook \
  /Users/james/.openclaw \
  /Users/james/agent-configs \
  /usr/local/etc \
  --exclude="*.pyc" \
  --exclude="node_modules" \
  --exclude=".ollama/models"  # Models can be re-downloaded

# Automated daily backup via launchd
cat > ~/Library/LaunchAgents/com.ai.restic-backup.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ai.restic-backup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/restic-backup.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
PLIST
```

**Backup script (`/usr/local/bin/restic-backup.sh`):**

```bash
#!/bin/bash
set -euo pipefail

export B2_ACCOUNT_ID="your-account-id"
export B2_ACCOUNT_KEY="your-account-key"
REPO="b2:your-bucket:ai-server"
LOG="/var/log/restic-backup.log"

echo "=== Backup started $(date) ===" >> "$LOG"

restic -r "$REPO" backup \
  /Users/james/openclaw-playbook \
  /Users/james/.openclaw \
  /Users/james/agent-configs \
  /Users/james/scripts \
  /usr/local/etc \
  --exclude-caches \
  --exclude="*.pyc" \
  --exclude="node_modules" \
  --exclude=".ollama/models" \
  --exclude="*.tmp" \
  >> "$LOG" 2>&1

# Prune old snapshots: keep 7 daily, 4 weekly, 6 monthly
restic -r "$REPO" forget \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 6 \
  --prune \
  >> "$LOG" 2>&1

echo "=== Backup completed $(date) ===" >> "$LOG"

# Send notification via Telegram bot
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d text="Backup completed successfully at $(date)"
```

### What to Back Up vs What to Skip

| Back Up | Skip (Re-downloadable) |
|---------|----------------------|
| `~/.openclaw/` (configs, memory, skills) | `~/.ollama/models/` (large, re-pullable) |
| `~/openclaw-playbook/` (your entire project) | `~/ComfyUI/models/` (large, re-downloadable) |
| `~/agent-configs/` | `node_modules/` |
| Docker volumes (configs) | Docker images (re-pullable) |
| `~/.ssh/` (if not using Tailscale SSH) | `*.pyc`, `__pycache__/` |
| Grafana dashboards | Prometheus TSDB (rebuild from metrics) |
| ChromaDB data directory | Homebrew (reinstall from Brewfile) |
| Custom scripts in `/usr/local/bin/` | |
| LaunchDaemon/Agent plists | |

### Disaster Recovery Plan

**If the Mac Studio dies completely:**

1. **Get replacement hardware** (same or similar Mac)
2. **Restore macOS** (Internet Recovery or USB installer)
3. **Install Tailscale** (Homebrew daemon variant, authenticate with pre-auth key)
4. **Restore from Restic:**
   ```bash
   brew install restic
   restic -r b2:your-bucket:ai-server restore latest --target /
   ```
5. **Reinstall Homebrew packages:**
   ```bash
   # If you maintain a Brewfile
   brew bundle install --file=~/openclaw-playbook/Brewfile
   ```
6. **Re-pull models:**
   ```bash
   ollama pull llama3.3:70b
   ollama pull codellama:70b
   # etc.
   ```
7. **Restart services:**
   ```bash
   sudo brew services start tailscale
   # Load LaunchDaemons
   sudo launchctl load /Library/LaunchDaemons/com.ai.*.plist
   ```

### Brewfile for Reproducible Setup

```ruby
# ~/openclaw-playbook/Brewfile
brew "tailscale"
brew "ollama"
brew "restic"
brew "vladkens/tap/macmon"
brew "steipete/tap/imsg"
brew "signal-cli"
brew "python@3.12"
brew "node"
brew "git"
brew "jq"
brew "htop"

cask "docker"          # or "orbstack"
cask "screens-5"       # VNC client (optional)
```

### References
- [Restic: Encrypted Offsite Backup](https://helgeklein.com/blog/restic-encrypted-offsite-backup-for-your-homeserver/)
- [Duplicacy vs Restic vs Borg (2025)](https://mangohost.net/blog/duplicacy-vs-restic-vs-borg-which-backup-tool-is-right-in-2025/)
- [BorgBase: Hosted Borg/Restic Repos](https://www.borgbase.com/)
- [rsync.net Cloud Storage](https://www.rsync.net/resources/howto/mac.html)
- [Linux Backup Strategies: rsync, Borg, Restic](https://dasroot.net/posts/2026/02/linux-backup-strategies-rsync-borg-restic/)
- [macOS Tahoe Time Machine Guide](https://www.sweetwater.com/sweetcare/articles/macos-tahoe-26-time-machine-backup-guide/)

---

## Quick Reference: The Full Stack

```
                    YOUR PHONE
                    (Telegram / iMessage / Signal)
                         |
                    TAILSCALE MESH
                    (WireGuard encrypted)
                         |
        +----------------+----------------+
        |                |                |
   Tailscale SSH    VNC/Screen       Tailscale Serve
   (CLI tasks)      Sharing          (Web dashboards)
        |           (GUI tasks)           |
        +--------+---+---+--------+------+
                 |       |        |
              AI STUDIO (Mac Studio M3 Ultra)
              +---------+---------+
              |         |         |
           Ollama    OpenClaw    Docker
           (native)  (native)   (containers)
              |         |         |
           Models    Agent      SearXNG
           (Metal    Skills     ChromaDB
            GPU)     Memory     Grafana
                     Configs    Homepage
                                Prometheus
```

### Startup Order

1. macOS boots (auto-restart after power failure)
2. Tailscale daemon starts (LaunchDaemon, pre-auth key)
3. Ollama starts (LaunchDaemon)
4. Docker starts (Login Item)
5. Docker Compose services start (restart: always)
6. OpenClaw starts (LaunchDaemon or LaunchAgent)
7. Tailscale Serve exposes dashboards
8. Health check runs and reports via Telegram

### Daily Operations

- **SSH in:** `tailscale ssh james@ai-studio`
- **Check status:** `/status` via Telegram bot
- **View dashboard:** `https://ai-studio.your-tailnet.ts.net/`
- **Monitor GPU:** `macmon` via SSH or `/gpu` via Telegram
- **Backups:** Automated at 3 AM via Restic to Backblaze B2
- **Maintenance restart:** Automated weekly at 4 AM Sunday
