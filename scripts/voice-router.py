#!/usr/bin/env python3
"""voice-router.py — Persistent daemon: mic → transcribe → route → speak.

The Voice Hub daemon listens for voice commands, transcribes them using
mlx-whisper, routes to the appropriate OpenClaw agent, and speaks the
response using Piper TTS.

Usage:
    python3 scripts/voice-router.py
    python3 scripts/voice-router.py --gateway http://localhost:18789
    python3 scripts/voice-router.py --no-tts  # Text output only (testing)
"""

import argparse
import io
import json
import logging
import os
import signal
import struct
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import sounddevice as sd

# Conditional imports — graceful degradation
try:
    import webrtcvad
    HAS_VAD = True
except ImportError:
    HAS_VAD = False
    print("WARNING: webrtcvad not available — using energy-based VAD", file=sys.stderr)

try:
    import mlx_whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
    print("ERROR: mlx_whisper not available — transcription disabled", file=sys.stderr)

try:
    import piper
    HAS_PIPER = True
except ImportError:
    HAS_PIPER = False
    print("WARNING: piper not available — falling back to macOS 'say'", file=sys.stderr)

# --- Configuration ---
SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_DURATION_MS = 30  # WebRTC VAD frame size
SILENCE_THRESHOLD_S = 1.5  # Seconds of silence to end recording
MAX_RECORDING_S = 30  # Max recording length
VAD_AGGRESSIVENESS = 2  # 0-3, higher = more aggressive filtering
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
MAX_RESPONSE_WORDS = 150  # ~30 seconds of speech

# --- Data paths ---
DATA_DIR = Path.home() / "jarvis" / "data" / "voice"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
COMMAND_LOG = DATA_DIR / "command-log.jsonl"
CONFIG_DIR = Path(__file__).parent / "voice-hub"
PIPER_CONFIG = CONFIG_DIR / "piper-config.json"

# --- Intent routing table ---
INTENT_ROUTES = {
    "deal-scanner": ["deal", "deals", "listing", "listings", "acquisition", "bizbuysell", "flippa"],
    "newsletter-engine": ["newsletter", "email blast", "subscriber", "subscribers"],
    "reputation-monitor": ["review", "reviews", "reputation", "rating", "ratings", "yelp", "healthgrades"],
    "compliance-engine": ["compliance", "regulation", "hipaa", "cms", "regulatory"],
    "outreach-agent": ["outreach", "cold email", "lead", "leads", "prospect"],
    "overnight-deliverables": ["deliverable", "deliverables", "order", "orders", "document"],
    "content-studio": ["content", "blog", "article", "seo", "post"],
    "system-guardian": ["system", "server", "status", "health", "infrastructure", "docker", "ollama"],
    "print-designer": ["print", "3d", "model", "stl", "printer"],
    "argument-simulator": ["decision", "should i", "analyze", "evaluate", "argument", "stress test"],
    "zombie-resurrector": ["zombie", "abandoned", "old repo", "resurrect", "dead project"],
    "codebase-archaeologist": ["codebase", "due diligence", "audit code", "archaeology", "analyze repo"],
    "template-publisher": ["template", "package", "sell", "gumroad", "publish"],
    "microtool-factory": ["microtool", "build tool", "scaffold", "healthcare tool"],
}

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(Path.home() / "jarvis" / "logs" / "voice-hub.log"),
    ],
)
log = logging.getLogger("voice-hub")


class VoiceRouter:
    """Main voice routing daemon."""

    def __init__(self, gateway_url: str, tts_enabled: bool = True):
        self.gateway_url = gateway_url.rstrip("/")
        self.tts_enabled = tts_enabled
        self.running = True
        self.vad = None
        self.piper_config = {}

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # Create data directories
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Initialize VAD
        if HAS_VAD:
            self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

        # Load Piper config
        if PIPER_CONFIG.exists():
            self.piper_config = json.loads(PIPER_CONFIG.read_text())

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        log.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def listen_for_speech(self) -> Optional[np.ndarray]:
        """Listen for speech using VAD, return audio buffer when speech ends."""
        frame_size = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
        frames = []
        silent_frames = 0
        speech_detected = False
        max_frames = int(MAX_RECORDING_S * 1000 / FRAME_DURATION_MS)
        silence_limit = int(SILENCE_THRESHOLD_S * 1000 / FRAME_DURATION_MS)

        log.debug("Listening...")

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype="int16", blocksize=frame_size) as stream:
                for _ in range(max_frames):
                    if not self.running:
                        return None

                    audio_data, overflowed = stream.read(frame_size)
                    if overflowed:
                        log.warning("Audio buffer overflow")

                    frame = audio_data.flatten()

                    # Detect speech
                    is_speech = self._is_speech(frame)

                    if is_speech:
                        speech_detected = True
                        silent_frames = 0
                        frames.append(frame)
                    elif speech_detected:
                        silent_frames += 1
                        frames.append(frame)  # Keep some silence for natural endings

                        if silent_frames >= silence_limit:
                            log.info(f"Speech ended ({len(frames)} frames)")
                            break
                    # If no speech detected yet, keep listening (don't accumulate frames)

        except sd.PortAudioError as e:
            log.error(f"Microphone error: {e}")
            return None

        if not speech_detected or len(frames) < 5:
            return None

        return np.concatenate(frames)

    def _is_speech(self, frame: np.ndarray) -> bool:
        """Detect if audio frame contains speech."""
        if self.vad and HAS_VAD:
            try:
                raw_bytes = frame.tobytes()
                return self.vad.is_speech(raw_bytes, SAMPLE_RATE)
            except Exception:
                pass

        # Fallback: energy-based detection
        energy = np.sqrt(np.mean(frame.astype(float) ** 2))
        return energy > 500  # Threshold — tune for your environment

    def transcribe(self, audio: np.ndarray) -> Optional[str]:
        """Transcribe audio using mlx-whisper."""
        if not HAS_WHISPER:
            log.error("Whisper not available")
            return None

        try:
            # Convert to float32 for Whisper
            audio_float = audio.astype(np.float32) / 32768.0

            result = mlx_whisper.transcribe(
                audio_float,
                path_or_hf_repo=WHISPER_MODEL,
                language="en",
            )

            text = result.get("text", "").strip()
            if text:
                log.info(f"Transcribed: {text}")
            return text if text else None

        except Exception as e:
            log.error(f"Transcription error: {e}")
            return None

    def route_intent(self, text: str) -> Optional[str]:
        """Match transcribed text to an agent ID."""
        text_lower = text.lower()

        for agent_id, triggers in INTENT_ROUTES.items():
            for trigger in triggers:
                if trigger in text_lower:
                    log.info(f"Routed to: {agent_id} (trigger: '{trigger}')")
                    return agent_id

        log.info("No agent match found")
        return None

    def send_to_agent(self, agent_id: str, message: str) -> Optional[str]:
        """Send message to OpenClaw agent via gateway API."""
        try:
            api_token = os.environ.get("OPENCLAW_API_TOKEN", "")
            response = httpx.post(
                f"{self.gateway_url}/api/agents/{agent_id}/message",
                json={"message": message},
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", data.get("message", str(data)))

        except httpx.TimeoutException:
            log.warning(f"Agent {agent_id} timed out")
            return f"The {agent_id.replace('-', ' ')} is taking too long. I'll send the result to Telegram."
        except httpx.HTTPError as e:
            log.error(f"API error: {e}")
            return f"The {agent_id.replace('-', ' ')} isn't responding."

    def format_for_speech(self, text: str) -> str:
        """Truncate and format agent response for TTS."""
        if not text:
            return "No response received."

        # Remove markdown formatting
        text = text.replace("**", "").replace("*", "").replace("#", "")
        text = text.replace("```", "").replace("`", "")
        text = text.replace("\n\n", ". ").replace("\n", ". ")

        # Truncate to word limit
        words = text.split()
        if len(words) > MAX_RESPONSE_WORDS:
            text = " ".join(words[:MAX_RESPONSE_WORDS])
            text += ". Full response sent to Telegram."

        return text

    def speak(self, text: str):
        """Speak text using Piper TTS or macOS say fallback."""
        if not self.tts_enabled:
            print(f"[TTS]: {text}")
            return

        if HAS_PIPER:
            try:
                voice = self.piper_config.get("voice", "en_US-lessac-medium")
                speaking_rate = self.piper_config.get("speakingRate", 1.0)

                # Use piper CLI
                proc = subprocess.Popen(
                    ["piper", "--model", voice, "--output-raw"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                audio_data, _ = proc.communicate(input=text.encode("utf-8"))

                # Play with sox
                subprocess.run(
                    ["play", "-r", "22050", "-e", "signed", "-b", "16", "-c", "1",
                     "-t", "raw", "-"],
                    input=audio_data,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception as e:
                log.warning(f"Piper TTS failed: {e}, falling back to macOS 'say'")

        # Fallback: macOS say command
        try:
            subprocess.run(["say", text], check=True, timeout=30)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            log.error(f"TTS fallback failed: {e}")
            print(f"[TTS]: {text}")

    def log_command(self, transcription: str, agent_id: Optional[str],
                    response_summary: str):
        """Write to the command log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "transcription": transcription,
            "agentId": agent_id,
            "responseSummary": response_summary[:200],
        }

        with open(COMMAND_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def run(self):
        """Main daemon loop."""
        log.info("Voice Hub starting...")
        log.info(f"Gateway: {self.gateway_url}")
        log.info(f"TTS: {'enabled' if self.tts_enabled else 'disabled'}")
        log.info(f"VAD: {'webrtcvad' if HAS_VAD else 'energy-based'}")
        log.info(f"Whisper: {'ready' if HAS_WHISPER else 'NOT AVAILABLE'}")
        log.info(f"Piper: {'ready' if HAS_PIPER else 'fallback to macOS say'}")
        log.info("")
        log.info("Listening for commands... (Ctrl+C to stop)")

        if not HAS_WHISPER:
            log.error("Cannot start without Whisper. Install with: pip install mlx-whisper")
            return

        while self.running:
            try:
                # Listen for speech
                audio = self.listen_for_speech()
                if audio is None:
                    continue

                # Transcribe
                text = self.transcribe(audio)
                if not text:
                    self.speak("I didn't catch that, please repeat.")
                    continue

                # Route to agent
                agent_id = self.route_intent(text)

                if agent_id is None:
                    self.speak("I didn't catch which agent you need. Say the agent name or describe what you want.")
                    self.log_command(text, None, "no_match")
                    continue

                # Confirm routing
                agent_name = agent_id.replace("-", " ")
                self.speak(f"Sending to {agent_name}.")

                # Send to agent
                response = self.send_to_agent(agent_id, text)

                # Format and speak response
                spoken_response = self.format_for_speech(response or "")
                self.speak(spoken_response)

                # Log
                self.log_command(text, agent_id, spoken_response)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Unexpected error: {e}", exc_info=True)
                time.sleep(1)  # Prevent tight error loop

        log.info("Voice Hub stopped.")


def main():
    parser = argparse.ArgumentParser(description="OpenClaw Voice Hub daemon")
    parser.add_argument("--gateway", default="http://localhost:18789",
                        help="OpenClaw gateway URL")
    parser.add_argument("--no-tts", action="store_true",
                        help="Disable TTS (text output only)")
    args = parser.parse_args()

    router = VoiceRouter(
        gateway_url=args.gateway,
        tts_enabled=not args.no_tts,
    )
    router.run()


if __name__ == "__main__":
    main()
