# Voice Hub — Operating Instructions

## Mission

Provide a persistent voice interface to the entire OpenClaw agent ecosystem. Listen for voice commands via the local microphone, transcribe with Whisper, route to the appropriate agent, and speak the response via Piper TTS. The user should be able to interact with any agent hands-free.

## Architecture

```
Microphone → VAD (Voice Activity Detection)
           → mlx-whisper (Speech-to-Text)
           → Intent Router (keyword matching)
           → OpenClaw Agent (via gateway API)
           → Response Formatter (truncate for speech)
           → Piper TTS (Text-to-Speech)
           → Speaker Output
```

## Setup

Run `scripts/setup-voice-hub.sh` to install all dependencies:
- **mlx-whisper**: Apple Silicon optimized Whisper model for STT
- **Piper TTS**: Local neural TTS engine (no cloud dependency)
- **sox**: Audio recording and processing
- **ffmpeg**: Audio format conversion
- **sounddevice**: Python audio I/O
- **webrtcvad**: Voice activity detection

## Intent Routing Table

| Trigger Phrase | Agent ID | Description |
|---------------|----------|-------------|
| "deal", "deals", "listings", "acquisition" | deal-scanner | Business deal queries |
| "newsletter", "email blast", "subscriber" | newsletter-engine | Newsletter operations |
| "review", "reputation", "rating" | reputation-monitor | Review monitoring |
| "compliance", "regulation", "hipaa", "cms" | compliance-engine | Compliance queries |
| "outreach", "cold email", "lead" | outreach-agent | Lead generation |
| "deliverable", "order", "document" | overnight-deliverables | Deliverable status |
| "content", "blog", "article", "seo" | content-studio | Content creation |
| "system", "server", "status", "health" | system-guardian | Infrastructure status |
| "print", "3d", "model", "stl" | print-designer | 3D print requests |
| "decision", "should i", "analyze", "evaluate" | argument-simulator | Decision analysis |
| "zombie", "abandoned", "old repo" | zombie-resurrector | Repo resurrection |
| "codebase", "due diligence", "audit code" | codebase-archaeologist | Code analysis |
| "template", "package", "sell", "gumroad" | template-publisher | Template packaging |
| "microtool", "build tool", "scaffold" | microtool-factory | Tool generation |

If no trigger phrase matches, default to a general query: "I didn't catch which agent you need. Say the agent name or describe what you want."

## Voice Interaction Flow

1. **Wake**: Voice Hub runs as a persistent daemon. VAD detects speech onset.
2. **Listen**: Record audio until 1.5 seconds of silence (configurable).
3. **Transcribe**: Send audio buffer to mlx-whisper. Get text transcription.
4. **Confirm**: Speak back: "Sending to [agent name]." (for commands) or "What did you mean?" (for ambiguous input)
5. **Route**: POST the transcribed command to the OpenClaw gateway API targeting the matched agent.
6. **Receive**: Get the agent's text response from the API.
7. **Format**: Truncate response for speech (max 30 seconds ≈ 150 words). If longer, speak summary and say "Full response saved to Telegram."
8. **Speak**: Pipe formatted response through Piper TTS to the speaker.
9. **Log**: Write transcript entry to command log.

## Voice Configuration

- **Whisper model**: `mlx-community/whisper-large-v3-turbo` (best accuracy/speed on Apple Silicon)
- **Piper voice**: `en_US-lessac-medium` (clear, professional, fast synthesis)
- **Sample rate**: 16000 Hz (Whisper native)
- **VAD aggressiveness**: 2 (of 0-3 scale; balanced sensitivity)
- **Silence threshold**: 1.5 seconds (end of utterance detection)
- **Max recording**: 30 seconds (prevent runaway recordings)
- **TTS speaking rate**: 1.0x (configurable in piper-config.json)

## Output Format

Voice responses follow these rules:
- **Max 30 seconds of speech** (~150 words) — if the agent returns more, summarize
- **Lead with the answer** — "You have 3 new deals" not "I checked the deal scanner and found..."
- **Use numbers explicitly** — "one hundred twenty thousand dollars" not "$120K"
- **Spell out abbreviations** — "S-D-E multiple" not "SDE multiple"
- **Confirm destructive actions** — "Are you sure you want to [X]? Say yes to confirm."

## Running as a Daemon

Voice Hub runs as a macOS launchd service:
- **Label**: `com.openclaw.voice-hub`
- **Script**: `python3 scripts/voice-router.py`
- **Auto-restart**: Yes, on crash
- **Log**: `~/jarvis/logs/voice-hub.log`

## Error Handling

- If the microphone is unavailable, log error and retry every 30 seconds
- If Whisper transcription fails, say "I didn't catch that, please repeat"
- If the target agent is unreachable, say "The [agent name] isn't responding. I'll send your request to Telegram instead."
- If Piper TTS fails, fall back to macOS `say` command
- Never crash the daemon — catch all exceptions, log them, and continue listening

## Escalation

- **Multiple consecutive transcription failures**: Alert System Guardian — possible microphone hardware issue
- **Agent timeout** (>60 seconds): Speak "Still working on it" and send result to Telegram when ready
- **Unrecognized commands** (3+ in a row): Suggest "Say 'help' for a list of available commands"

## Data Storage

- Save transcripts to `~/jarvis/data/voice/transcripts/` as `{YYYY-MM-DD}-transcript.jsonl`
- Maintain command log at `~/jarvis/data/voice/command-log.jsonl` with timestamp, transcription, matched agent, response summary

---

## Jarvis Conversational Mode

In addition to the keyword-based command router above, the Voice Hub supports a **conversational mode** via `jarvis-voice.py`. This is a ChatGPT-voice-style experience: push-to-talk, natural conversation, streaming TTS responses, and rolling memory.

### How It Works

```
Push-to-talk (Cmd+Shift+J)
    → Mic + VAD (record until 1.5s silence)
    → mlx-whisper (speech-to-text)
    → Ollama streaming (qwen3:30b-a3b, /api/chat, stream=true)
    → Sentence buffer (split stream into sentences)
    → Piper TTS (synthesize each sentence as it arrives)
    → Speaker (play sentence-by-sentence)
```

### Key Differences from Command Router

| Feature | Command Router (`voice-router.py`) | Conversational (`jarvis-voice.py`) |
|---------|------------------------------------|------------------------------------|
| Activation | Always listening (VAD) | Push-to-talk (Cmd+Shift+J) |
| Routing | Keyword matching | LLM decides via `[ROUTE:agent-id]` tag |
| Conversation | Stateless (single command) | Rolling memory (20 turns) |
| TTS | Full response after agent replies | Streaming sentence-by-sentence |
| Direct answers | Never — always routes to agent | Handles general questions directly |
| Persona | Switchboard operator (SOUL.md) | Conversational assistant (SOUL-jarvis.md) |

### Running Jarvis Conversational Mode

```bash
# Manual (foreground)
source ~/jarvis/venvs/voice-hub/bin/activate
python3 scripts/jarvis-voice.py

# Test streaming pipeline (no mic)
python3 scripts/jarvis-voice.py --test-pipeline "Tell me a joke"

# Test hotkey registration
python3 scripts/jarvis-voice.py --test-hotkey

# As launchd daemon
launchctl load ~/Library/LaunchAgents/com.openclaw.jarvis-voice.plist
```

### Voice Commands

- **"New conversation"** / **"start over"** — clears conversation memory
- **"Forget that"** / **"scratch that"** — removes the last exchange
- **"What did I just ask?"** — repeats your last question
- **"Say that again"** — repeats Jarvis's last response

### Smart Routing

Jarvis decides when to route to a specialist agent. The LLM outputs `[ROUTE:agent-id]` at the start of its response when a specialist would do better. The pipeline detects this, cancels the Ollama stream, speaks a bridge phrase ("Let me check with Deal Scanner"), calls the gateway API, and speaks the agent's response.

### Configuration

- Runtime config: `scripts/voice-hub/jarvis-config.json`
- System prompt: `scripts/voice-hub/jarvis-system-prompt.md`
- Persona: `agent-configs/workspaces/voice-hub/SOUL-jarvis.md`
- Logs: `~/jarvis/logs/jarvis-voice.log`
- Command log: `~/jarvis/data/voice/jarvis-command-log.jsonl`
- Conversation history: `~/jarvis/data/voice/conversation-history.json`
