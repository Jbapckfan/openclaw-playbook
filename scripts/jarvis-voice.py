#!/usr/bin/env python3
"""jarvis-voice.py — Conversational Jarvis voice agent with streaming TTS.

Push-to-talk (Cmd+Shift+J) → mic → whisper → Ollama streaming → sentence
buffer → Piper TTS → speaker. Supports rolling conversation memory and
smart routing to specialist agents.

Usage:
    python3 scripts/jarvis-voice.py
    python3 scripts/jarvis-voice.py --test-pipeline "Tell me a joke"
    python3 scripts/jarvis-voice.py --test-hotkey
    python3 scripts/jarvis-voice.py --no-tts
"""

import argparse
import io
import json
import logging
import math
import os
import queue
import re
import signal
import struct
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime, timezone
from enum import Enum, auto
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

try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    print("ERROR: pynput not available — hotkey disabled", file=sys.stderr)

# --- Paths ---
SCRIPT_DIR = Path(__file__).parent
CONFIG_DIR = SCRIPT_DIR / "voice-hub"
CONFIG_FILE = CONFIG_DIR / "jarvis-config.json"
SYSTEM_PROMPT_FILE = CONFIG_DIR / "jarvis-system-prompt.md"
PIPER_CONFIG_FILE = CONFIG_DIR / "piper-config.json"
LLM_PROVIDERS_FILE = SCRIPT_DIR.parent / "agent-configs" / "llm-providers.json"
ENV_FILE = Path.home() / ".jarvis" / ".env"
DATA_DIR = Path.home() / "jarvis" / "data" / "voice"
LOG_DIR = Path.home() / "jarvis" / "logs"

# --- Load .env file ---
def load_env_file():
    """Load environment variables from ~/.jarvis/.env if it exists."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and value and key not in os.environ:
                os.environ[key] = value

load_env_file()

# --- Load config ---
def load_config() -> dict:
    """Load jarvis-config.json with defaults."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}

CONFIG = load_config()

# --- Extract config values ---
LLM_MODEL = CONFIG.get("llm", {}).get("model", "qwen3:30b-a3b")
LLM_BASE_URL = CONFIG.get("llm", {}).get("baseUrl", "http://localhost:11434")
LLM_TEMPERATURE = CONFIG.get("llm", {}).get("temperature", 0.7)
LLM_MAX_TOKENS = CONFIG.get("llm", {}).get("maxTokens", 1024)
LLM_STREAM_TIMEOUT = CONFIG.get("llm", {}).get("streamTimeoutMs", 30000) / 1000

SAMPLE_RATE = CONFIG.get("stt", {}).get("sampleRate", 16000)
CHANNELS = 1
FRAME_DURATION_MS = 30
SILENCE_THRESHOLD_S = CONFIG.get("stt", {}).get("silenceThresholdS", 1.5)
MAX_RECORDING_S = CONFIG.get("stt", {}).get("maxRecordingS", 60)
VAD_AGGRESSIVENESS = CONFIG.get("stt", {}).get("vadAggressiveness", 2)
WHISPER_MODEL = CONFIG.get("stt", {}).get("model", "mlx-community/whisper-large-v3-turbo")

TTS_VOICE = CONFIG.get("tts", {}).get("voice", "en_US-lessac-medium")
TTS_SAMPLE_RATE = CONFIG.get("tts", {}).get("sampleRate", 22050)
TTS_SPEAKING_RATE = CONFIG.get("tts", {}).get("speakingRate", 1.0)
TTS_FALLBACK = CONFIG.get("tts", {}).get("fallback", "say")

MAX_TURNS = CONFIG.get("conversation", {}).get("maxTurns", 20)
HISTORY_FILE = Path(
    CONFIG.get("conversation", {}).get("historyFile", "~/jarvis/data/voice/conversation-history.json")
    .replace("~", str(Path.home()))
)
VOICE_CMD_CLEAR = CONFIG.get("conversation", {}).get("voiceCommands", {}).get(
    "clearMemory", ["new conversation", "start over", "clear history", "reset"]
)
VOICE_CMD_FORGET = CONFIG.get("conversation", {}).get("voiceCommands", {}).get(
    "forgetLast", ["forget that", "undo that", "never mind", "scratch that"]
)

GATEWAY_URL = CONFIG.get("routing", {}).get("gatewayUrl", "http://localhost:18789")
BRIDGE_PHRASES = CONFIG.get("routing", {}).get("bridgePhrases", [
    "Let me check with {agent}.",
    "Routing to {agent}.",
    "Asking {agent} for you.",
])
ROUTE_DETECTION_CHARS = CONFIG.get("routing", {}).get("routeDetectionChars", 50)

BEEP_ENABLED = CONFIG.get("audio", {}).get("activationBeep", True)
BEEP_FREQ = CONFIG.get("audio", {}).get("beepFrequency", 880)
BEEP_DURATION = CONFIG.get("audio", {}).get("beepDuration", 0.1)
DEACTIVATION_FREQ = CONFIG.get("audio", {}).get("deactivationFrequency", 440)
DEACTIVATION_DURATION = CONFIG.get("audio", {}).get("deactivationDuration", 0.08)

LOG_LEVEL = CONFIG.get("logging", {}).get("level", "INFO")
LOG_FILE = Path(
    CONFIG.get("logging", {}).get("logFile", "~/jarvis/logs/jarvis-voice.log")
    .replace("~", str(Path.home()))
)
COMMAND_LOG = Path(
    CONFIG.get("logging", {}).get("commandLog", "~/jarvis/data/voice/jarvis-command-log.jsonl")
    .replace("~", str(Path.home()))
)

# --- Load LLM providers (cloud fallbacks) ---
def load_llm_providers() -> list[dict]:
    """Load cloud LLM providers from llm-providers.json for fallback."""
    if not LLM_PROVIDERS_FILE.exists():
        return []
    try:
        data = json.loads(LLM_PROVIDERS_FILE.read_text())
        providers_by_id = {p["id"]: p for p in data.get("providers", [])}
        # Build fallback chain for voice agent
        voice_defaults = data.get("defaults", {}).get("voiceAgent", {})
        fallback_ids = voice_defaults.get("fallbackChain", ["groq", "cerebras", "sambanova"])
        preferred_models = voice_defaults.get("preferredModel", {})

        chain = []
        for pid in fallback_ids:
            if pid in providers_by_id:
                provider = providers_by_id[pid]
                # Resolve API key from environment variable
                api_key_env = provider.get("apiKeyEnv", "")
                api_key = os.environ.get(api_key_env, "") if api_key_env else ""
                if not api_key:
                    continue  # Skip providers without a configured key
                chain.append({
                    "id": pid,
                    "name": provider["name"],
                    "endpoint": provider["endpoint"],
                    "apiKey": api_key,
                    "compatible": provider.get("compatible", "openai"),
                    "model": preferred_models.get(pid, provider["models"][0] if provider.get("models") else ""),
                })
        return chain
    except (json.JSONDecodeError, KeyError) as e:
        print(f"WARNING: Failed to load LLM providers: {e}", file=sys.stderr)
        return []

CLOUD_FALLBACKS = load_llm_providers()

# --- Load system prompt ---
def load_system_prompt() -> str:
    """Load the system prompt from the markdown file."""
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text().strip()
    return "You are Jarvis, a concise conversational voice assistant. Keep responses short and natural for speech."

SYSTEM_PROMPT = load_system_prompt()

# --- Logging ---
LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("jarvis-voice")


# ============================================================
# State Machine
# ============================================================

class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


# ============================================================
# Conversation Memory
# ============================================================

class ConversationMemory:
    """Rolling window of conversation turns with persistence."""

    def __init__(self, max_turns: int = MAX_TURNS):
        self.max_turns = max_turns
        self.turns: list[dict] = []
        self._load()

    def _load(self):
        """Load conversation history from disk."""
        try:
            if HISTORY_FILE.exists():
                data = json.loads(HISTORY_FILE.read_text())
                self.turns = data.get("turns", [])
                log.info(f"Loaded {len(self.turns)} conversation turns")
        except (json.JSONDecodeError, KeyError):
            log.warning("Could not load conversation history, starting fresh")
            self.turns = []

    def _save(self):
        """Persist conversation history to disk."""
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
                "turns": self.turns,
            }
            HISTORY_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Failed to save conversation history: {e}")

    def add_user(self, text: str):
        """Add a user message."""
        self.turns.append({"role": "user", "content": text})
        self._trim()
        self._save()

    def add_assistant(self, text: str):
        """Add an assistant message."""
        self.turns.append({"role": "assistant", "content": text})
        self._trim()
        self._save()

    def _trim(self):
        """Keep only the last max_turns * 2 messages (user + assistant pairs)."""
        max_messages = self.max_turns * 2
        if len(self.turns) > max_messages:
            self.turns = self.turns[-max_messages:]

    def get_messages(self) -> list[dict]:
        """Return messages formatted for the Ollama API."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.turns)
        return messages

    def clear(self):
        """Clear all conversation history."""
        self.turns = []
        self._save()
        log.info("Conversation memory cleared")

    def forget_last(self):
        """Remove the last user/assistant exchange."""
        # Remove last assistant message if present
        if self.turns and self.turns[-1]["role"] == "assistant":
            self.turns.pop()
        # Remove last user message if present
        if self.turns and self.turns[-1]["role"] == "user":
            self.turns.pop()
        self._save()
        log.info("Last exchange forgotten")


# ============================================================
# Sentence Splitter
# ============================================================

# Abbreviations that shouldn't trigger sentence splits
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "ave",
    "inc", "ltd", "corp", "dept", "est", "approx", "etc",
    "vs", "fig", "vol", "no", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}

def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, handling abbreviations and decimals.

    Splits on . ! ? followed by a space and uppercase letter (or end of string),
    but avoids splitting on abbreviations (Dr., Mr.) and decimals (3.14).
    """
    if not text.strip():
        return []

    sentences = []
    current = []
    words = text.split()

    for i, word in enumerate(words):
        current.append(word)

        # Check if word ends with sentence-ending punctuation
        if word and word[-1] in ".!?":
            # Check if it's an abbreviation
            base = word.rstrip(".!?").lower()
            if base in ABBREVIATIONS:
                continue

            # Check if it's a decimal number (next word starts with digit)
            if word[-1] == "." and i + 1 < len(words) and words[i + 1][:1].isdigit():
                continue

            # Check if the base is a number with a period (e.g., "3.")
            if word[-1] == "." and base.replace(",", "").replace(".", "").isdigit():
                continue

            # It's a real sentence boundary
            sentence = " ".join(current).strip()
            if sentence:
                sentences.append(sentence)
            current = []

    # Remaining words form the last sentence
    if current:
        sentence = " ".join(current).strip()
        if sentence:
            sentences.append(sentence)

    return sentences


# ============================================================
# Audio Utilities
# ============================================================

def play_beep(frequency: float = BEEP_FREQ, duration: float = BEEP_DURATION):
    """Play a short beep to indicate activation/deactivation."""
    if not BEEP_ENABLED:
        return
    try:
        t = np.linspace(0, duration, int(44100 * duration), endpoint=False)
        # Apply fade-in/out envelope to prevent clicks
        envelope = np.ones_like(t)
        fade_samples = min(int(44100 * 0.01), len(t) // 4)
        if fade_samples > 0:
            envelope[:fade_samples] = np.linspace(0, 1, fade_samples)
            envelope[-fade_samples:] = np.linspace(1, 0, fade_samples)
        wave_data = (0.3 * np.sin(2 * np.pi * frequency * t) * envelope).astype(np.float32)
        sd.play(wave_data, samplerate=44100, blocking=True)
    except Exception as e:
        log.debug(f"Beep failed: {e}")


def _is_speech(frame: np.ndarray, vad=None) -> bool:
    """Detect if audio frame contains speech."""
    if vad and HAS_VAD:
        try:
            raw_bytes = frame.tobytes()
            return vad.is_speech(raw_bytes, SAMPLE_RATE)
        except Exception:
            pass
    # Fallback: energy-based detection
    energy = np.sqrt(np.mean(frame.astype(float) ** 2))
    return energy > 500


def format_for_speech(text: str) -> str:
    """Clean text for TTS output — remove markdown formatting."""
    if not text:
        return ""
    text = text.replace("**", "").replace("*", "").replace("#", "")
    text = text.replace("```", "").replace("`", "")
    text = text.replace("\n\n", ". ").replace("\n", ". ")
    # Collapse multiple periods/spaces
    text = re.sub(r"\.(\s*\.)+", ".", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# ============================================================
# Streaming Pipeline
# ============================================================

class StreamingPipeline:
    """Three-thread pipeline: Ollama stream → sentence buffer → TTS → speaker.

    Threads communicate via queues. A shared cancel Event allows interruption
    at any point in the pipeline.
    """

    def __init__(self, tts_enabled: bool = True):
        self.tts_enabled = tts_enabled
        self.cancel = threading.Event()
        self.sentence_queue: queue.Queue[Optional[str]] = queue.Queue()
        self.audio_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self.full_response = ""  # Accumulated for conversation memory
        self._piper_config = {}
        self._lock = threading.Lock()

        if PIPER_CONFIG_FILE.exists():
            try:
                self._piper_config = json.loads(PIPER_CONFIG_FILE.read_text())
            except json.JSONDecodeError:
                pass

    def run(self, messages: list[dict]) -> str:
        """Run the full streaming pipeline. Returns the complete response text."""
        self.cancel.clear()
        self.full_response = ""
        self.sentence_queue = queue.Queue()
        self.audio_queue = queue.Queue()

        # Start all three threads
        threads = [
            threading.Thread(target=self._stream_from_ollama, args=(messages,),
                             name="ollama-stream", daemon=True),
            threading.Thread(target=self._synthesize_sentences,
                             name="tts-synth", daemon=True),
            threading.Thread(target=self._play_audio_chunks,
                             name="audio-play", daemon=True),
        ]

        for t in threads:
            t.start()

        # Wait for completion (or cancellation)
        for t in threads:
            t.join(timeout=LLM_STREAM_TIMEOUT + 10)

        return self.full_response

    def interrupt(self):
        """Cancel the pipeline (e.g., user pressed PTT during playback)."""
        log.info("Pipeline interrupted")
        self.cancel.set()
        # Drain queues to unblock threads
        for q in (self.sentence_queue, self.audio_queue):
            try:
                while not q.empty():
                    q.get_nowait()
            except queue.Empty:
                pass
        # Send poison pills to unblock waiting threads
        self.sentence_queue.put(None)
        self.audio_queue.put(None)

    def _stream_from_ollama(self, messages: list[dict]):
        """Thread 1: Stream tokens from LLM, buffer into sentences.

        Tries Ollama first. If Ollama is unreachable, falls through to cloud
        providers (Groq → Cerebras → SambaNova) from llm-providers.json.
        """
        # Try Ollama first
        success = self._try_ollama_stream(messages)
        if success:
            return

        # Ollama failed — try cloud fallbacks
        if CLOUD_FALLBACKS and not self.cancel.is_set():
            log.info(f"Ollama unavailable, trying {len(CLOUD_FALLBACKS)} cloud fallbacks...")
            for provider in CLOUD_FALLBACKS:
                if self.cancel.is_set():
                    break
                success = self._try_cloud_stream(messages, provider)
                if success:
                    return

        # All providers failed
        if not self.cancel.is_set():
            self.sentence_queue.put("I can't reach any of my thinking engines right now.")
            with self._lock:
                self.full_response = "[error: all providers unreachable]"
            self.sentence_queue.put(None)

    def _try_ollama_stream(self, messages: list[dict]) -> bool:
        """Try streaming from local Ollama. Returns True on success."""
        token_buffer = ""
        route_check_done = False

        try:
            with httpx.Client(timeout=httpx.Timeout(LLM_STREAM_TIMEOUT, connect=5)) as client:
                with client.stream(
                    "POST",
                    f"{LLM_BASE_URL}/api/chat",
                    json={
                        "model": LLM_MODEL,
                        "messages": messages,
                        "stream": True,
                        "options": {
                            "temperature": LLM_TEMPERATURE,
                            "num_predict": LLM_MAX_TOKENS,
                        },
                    },
                ) as response:
                    response.raise_for_status()

                    for line in response.iter_lines():
                        if self.cancel.is_set():
                            return True  # Cancelled counts as "handled"

                        if not line.strip():
                            continue

                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        token = data.get("message", {}).get("content", "")
                        if not token:
                            if data.get("done"):
                                break
                            continue

                        token_buffer += token

                        # Route detection + sentence emission
                        if self._process_token_buffer(token_buffer, route_check_done):
                            return True  # Route detected
                        if not route_check_done and len(token_buffer) > ROUTE_DETECTION_CHARS:
                            route_check_done = True

                        # Sentence splitting
                        token_buffer = self._emit_sentences(token_buffer)

                        if data.get("done"):
                            break

            # Flush remaining
            self._flush_buffer(token_buffer)
            self.sentence_queue.put(None)
            return True

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            log.warning(f"Ollama unavailable: {e}")
            return False
        except Exception as e:
            log.error(f"Ollama error: {e}", exc_info=True)
            return False

    def _try_cloud_stream(self, messages: list[dict], provider: dict) -> bool:
        """Try streaming from a cloud provider (OpenAI-compatible). Returns True on success."""
        pid = provider["id"]
        endpoint = provider["endpoint"]
        api_key = provider["apiKey"]
        model = provider["model"]
        compatible = provider.get("compatible", "openai")

        log.info(f"Trying cloud provider: {provider['name']} ({model})")

        if compatible == "google":
            # Google Gemini uses a different API format — skip for streaming
            log.info(f"Skipping {pid} (Google API not OpenAI-compatible for streaming)")
            return False

        token_buffer = ""
        route_check_done = False

        try:
            with httpx.Client(timeout=httpx.Timeout(LLM_STREAM_TIMEOUT, connect=10)) as client:
                with client.stream(
                    "POST",
                    f"{endpoint}/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": True,
                        "temperature": LLM_TEMPERATURE,
                        "max_tokens": LLM_MAX_TOKENS,
                    },
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                ) as response:
                    response.raise_for_status()

                    for line in response.iter_lines():
                        if self.cancel.is_set():
                            return True

                        if not line.strip():
                            continue

                        # SSE format: "data: {...}" or "data: [DONE]"
                        if line.startswith("data: "):
                            line = line[6:]
                        if line.strip() == "[DONE]":
                            break

                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        # OpenAI-compatible streaming format
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        token = delta.get("content", "")
                        if not token:
                            if choices[0].get("finish_reason"):
                                break
                            continue

                        token_buffer += token

                        if self._process_token_buffer(token_buffer, route_check_done):
                            return True
                        if not route_check_done and len(token_buffer) > ROUTE_DETECTION_CHARS:
                            route_check_done = True

                        token_buffer = self._emit_sentences(token_buffer)

            self._flush_buffer(token_buffer)
            self.sentence_queue.put(None)
            log.info(f"Cloud provider {pid} succeeded")
            return True

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            log.warning(f"Cloud provider {pid} unavailable: {e}")
            return False
        except httpx.HTTPStatusError as e:
            log.warning(f"Cloud provider {pid} HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            log.error(f"Cloud provider {pid} error: {e}")
            return False

    # --- Shared helpers for streaming ---

    def _process_token_buffer(self, token_buffer: str, route_check_done: bool) -> bool:
        """Check for route detection in token buffer. Returns True if route found."""
        if route_check_done:
            return False
        if len(token_buffer) > ROUTE_DETECTION_CHARS + 50:
            return False

        route_match = re.match(
            r"\s*\[ROUTE:([\w-]+)\]\s*(.*)",
            token_buffer,
            re.DOTALL,
        )
        if route_match:
            agent_id = route_match.group(1)
            refined_query = route_match.group(2).strip()
            log.info(f"Route detected: {agent_id}")

            with self._lock:
                self.full_response = f"[ROUTE:{agent_id}] {refined_query}"

            self.sentence_queue.put(f"__ROUTE__:{agent_id}:{refined_query}")
            self.sentence_queue.put(None)
            return True

        return False

    def _emit_sentences(self, token_buffer: str) -> str:
        """Split buffer into sentences, emit complete ones, return remainder."""
        cleaned = format_for_speech(token_buffer)
        sentences = split_into_sentences(cleaned)

        if len(sentences) > 1:
            for sent in sentences[:-1]:
                if sent.strip() and not self.cancel.is_set():
                    self.sentence_queue.put(sent)
                    with self._lock:
                        self.full_response += sent + " "
            return sentences[-1]

        return token_buffer

    def _flush_buffer(self, token_buffer: str):
        """Flush any remaining text in the buffer."""
        if token_buffer.strip() and not self.cancel.is_set():
            cleaned = format_for_speech(token_buffer)
            if cleaned:
                self.sentence_queue.put(cleaned)
                with self._lock:
                    self.full_response += cleaned

    def _synthesize_sentences(self):
        """Thread 2: Take sentences from queue, synthesize via Piper TTS."""
        while not self.cancel.is_set():
            try:
                sentence = self.sentence_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if sentence is None:
                # End of stream
                self.audio_queue.put(None)
                return

            if self.cancel.is_set():
                self.audio_queue.put(None)
                return

            # Check for routing sentinel
            if sentence.startswith("__ROUTE__:"):
                self.audio_queue.put(sentence)
                self.audio_queue.put(None)
                return

            if not self.tts_enabled:
                print(f"[TTS]: {sentence}")
                self.audio_queue.put(b"__SKIP__")
                continue

            # Synthesize with Piper
            audio_data = self._synthesize_one(sentence)
            if audio_data and not self.cancel.is_set():
                self.audio_queue.put(audio_data)

        # Cancelled
        self.audio_queue.put(None)

    def _synthesize_one(self, text: str) -> Optional[bytes]:
        """Synthesize a single sentence to raw audio bytes."""
        if HAS_PIPER:
            try:
                voice = self._piper_config.get("voice", TTS_VOICE)
                proc = subprocess.Popen(
                    ["piper", "--model", voice, "--output-raw"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                audio_data, _ = proc.communicate(input=text.encode("utf-8"), timeout=10)
                return audio_data
            except subprocess.TimeoutExpired:
                log.warning("Piper TTS timed out")
                proc.kill()
            except Exception as e:
                log.warning(f"Piper TTS failed: {e}")

        # Fallback: macOS say → capture to temp file
        if TTS_FALLBACK == "say":
            try:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
                    tmp_path = f.name
                subprocess.run(["say", "-o", tmp_path, text], check=True, timeout=10)
                with open(tmp_path, "rb") as f:
                    audio_data = f.read()
                os.unlink(tmp_path)
                return audio_data
            except Exception as e:
                log.warning(f"macOS say fallback failed: {e}")

        return None

    def _play_audio_chunks(self):
        """Thread 3: Play synthesized audio chunks sequentially."""
        while not self.cancel.is_set():
            try:
                audio_data = self.audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if audio_data is None:
                return

            if self.cancel.is_set():
                return

            # Routing sentinel — pass through (handled by caller)
            if isinstance(audio_data, str) and audio_data.startswith("__ROUTE__:"):
                return

            # Skip marker (no-TTS mode)
            if audio_data == b"__SKIP__":
                continue

            try:
                if HAS_PIPER:
                    # Raw 16-bit signed mono audio at Piper's sample rate
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    sd.play(audio_array, samplerate=TTS_SAMPLE_RATE, blocking=True)
                else:
                    # AIFF from macOS say — use afplay
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as f:
                        f.write(audio_data)
                        tmp_path = f.name
                    subprocess.run(["afplay", tmp_path], timeout=30)
                    os.unlink(tmp_path)
            except Exception as e:
                log.warning(f"Audio playback error: {e}")


# ============================================================
# Smart Routing
# ============================================================

AGENT_NAMES = {
    "deal-scanner": "Deal Scanner",
    "newsletter-engine": "Newsletter Engine",
    "reputation-monitor": "Reputation Monitor",
    "compliance-engine": "Compliance Engine",
    "outreach-agent": "Outreach Agent",
    "overnight-deliverables": "Overnight Deliverables",
    "content-studio": "Content Studio",
    "system-guardian": "System Guardian",
    "print-designer": "Print Designer",
    "argument-simulator": "Argument Simulator",
    "zombie-resurrector": "Zombie Resurrector",
    "codebase-archaeologist": "Codebase Archaeologist",
    "template-publisher": "Template Publisher",
    "microtool-factory": "Microtool Factory",
    "openclaw-core": "OpenClaw Core",
}


def send_to_agent(agent_id: str, message: str) -> Optional[str]:
    """Send message to OpenClaw agent via gateway API."""
    try:
        api_token = os.environ.get("OPENCLAW_API_TOKEN", "")
        response = httpx.post(
            f"{GATEWAY_URL}/api/agents/{agent_id}/message",
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
        return f"The {AGENT_NAMES.get(agent_id, agent_id)} is taking too long. I'll send the result to Telegram."
    except httpx.HTTPError as e:
        log.error(f"API error for {agent_id}: {e}")
        return f"The {AGENT_NAMES.get(agent_id, agent_id)} isn't responding right now."


def get_bridge_phrase(agent_id: str) -> str:
    """Get a random bridge phrase for routing."""
    import random
    agent_name = AGENT_NAMES.get(agent_id, agent_id.replace("-", " ").title())
    phrase = random.choice(BRIDGE_PHRASES)
    return phrase.format(agent=agent_name)


# ============================================================
# TTS Utility (non-streaming, for short phrases)
# ============================================================

def speak_simple(text: str, tts_enabled: bool = True):
    """Speak a short phrase (non-streaming). Used for beeps, confirmations, errors."""
    if not tts_enabled:
        print(f"[TTS]: {text}")
        return

    if HAS_PIPER:
        try:
            voice = TTS_VOICE
            if PIPER_CONFIG_FILE.exists():
                cfg = json.loads(PIPER_CONFIG_FILE.read_text())
                voice = cfg.get("voice", voice)

            proc = subprocess.Popen(
                ["piper", "--model", voice, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            audio_data, _ = proc.communicate(input=text.encode("utf-8"), timeout=10)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            sd.play(audio_array, samplerate=TTS_SAMPLE_RATE, blocking=True)
            return
        except Exception as e:
            log.warning(f"Piper TTS failed: {e}")

    # Fallback: macOS say
    try:
        subprocess.run(["say", text], check=True, timeout=30)
    except Exception as e:
        log.error(f"TTS fallback failed: {e}")
        print(f"[TTS]: {text}")


# ============================================================
# Jarvis Voice Agent
# ============================================================

class JarvisVoice:
    """Main conversational voice agent with push-to-talk."""

    def __init__(self, tts_enabled: bool = True, gateway_url: str = GATEWAY_URL):
        self.tts_enabled = tts_enabled
        self.gateway_url = gateway_url
        self.state = State.IDLE
        self.running = True
        self.memory = ConversationMemory()
        self.pipeline = StreamingPipeline(tts_enabled=tts_enabled)
        self.vad = None
        self._state_lock = threading.Lock()
        self._ptt_event = threading.Event()

        # Signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # VAD
        if HAS_VAD:
            self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    def _handle_signal(self, signum, frame):
        log.info(f"Received signal {signum}, shutting down...")
        self.running = False
        self._ptt_event.set()

    def _set_state(self, new_state: State):
        with self._state_lock:
            old = self.state
            self.state = new_state
            log.debug(f"State: {old.name} → {new_state.name}")

    def _get_state(self) -> State:
        with self._state_lock:
            return self.state

    # --- Push-to-Talk Hotkey ---

    def _setup_hotkey(self):
        """Set up pynput global hotkey listener for Cmd+Shift+J."""
        if not HAS_PYNPUT:
            log.error("pynput not installed — hotkey unavailable")
            return None

        # Track pressed modifier keys
        pressed_keys = set()

        def on_press(key):
            try:
                pressed_keys.add(key)

                # Check for Cmd+Shift+J
                is_cmd = (
                    keyboard.Key.cmd in pressed_keys
                    or keyboard.Key.cmd_l in pressed_keys
                    or keyboard.Key.cmd_r in pressed_keys
                )
                is_shift = (
                    keyboard.Key.shift in pressed_keys
                    or keyboard.Key.shift_l in pressed_keys
                    or keyboard.Key.shift_r in pressed_keys
                )
                is_j = (
                    hasattr(key, "char") and key.char
                    and key.char.lower() == "j"
                )

                if is_cmd and is_shift and is_j:
                    self._on_ptt_pressed()
            except AttributeError:
                pass

        def on_release(key):
            try:
                pressed_keys.discard(key)
            except (AttributeError, KeyError):
                pass

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        log.info("Hotkey registered: Cmd+Shift+J (push-to-talk)")
        return listener

    def _on_ptt_pressed(self):
        """Handle push-to-talk activation."""
        current = self._get_state()

        if current == State.SPEAKING:
            # Interrupt current speech and start recording
            log.info("PTT pressed during speech — interrupting")
            self.pipeline.interrupt()
            sd.stop()  # Stop any playing audio
            self._ptt_event.set()
            return

        if current == State.IDLE:
            self._ptt_event.set()
            return

        # If already recording or processing, ignore
        log.debug(f"PTT pressed in state {current.name} — ignored")

    # --- Recording ---

    def listen_for_speech(self, cancel_event: Optional[threading.Event] = None) -> Optional[np.ndarray]:
        """Listen for speech with VAD, return audio when speech ends."""
        frame_size = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
        frames = []
        silent_frames = 0
        speech_detected = False
        max_frames = int(MAX_RECORDING_S * 1000 / FRAME_DURATION_MS)
        silence_limit = int(SILENCE_THRESHOLD_S * 1000 / FRAME_DURATION_MS)

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype="int16", blocksize=frame_size) as stream:
                for _ in range(max_frames):
                    if not self.running:
                        return None
                    if cancel_event and cancel_event.is_set():
                        return None

                    audio_data, overflowed = stream.read(frame_size)
                    if overflowed:
                        log.warning("Audio buffer overflow")

                    frame = audio_data.flatten()
                    is_speech = _is_speech(frame, self.vad)

                    if is_speech:
                        speech_detected = True
                        silent_frames = 0
                        frames.append(frame)
                    elif speech_detected:
                        silent_frames += 1
                        frames.append(frame)

                        if silent_frames >= silence_limit:
                            log.info(f"Speech ended ({len(frames)} frames)")
                            break

        except sd.PortAudioError as e:
            log.error(f"Microphone error: {e}")
            return None

        if not speech_detected or len(frames) < 5:
            return None

        return np.concatenate(frames)

    def transcribe(self, audio: np.ndarray) -> Optional[str]:
        """Transcribe audio using mlx-whisper."""
        if not HAS_WHISPER:
            log.error("Whisper not available")
            return None

        try:
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

    # --- Voice Command Handling ---

    def _check_voice_command(self, text: str) -> Optional[str]:
        """Check if the transcription is a voice command. Returns command type or None."""
        text_lower = text.lower().strip()

        for phrase in VOICE_CMD_CLEAR:
            if phrase in text_lower:
                return "clear"

        for phrase in VOICE_CMD_FORGET:
            if phrase in text_lower:
                return "forget"

        if "what did i just ask" in text_lower or "what did i say" in text_lower:
            return "repeat_user"

        if "say that again" in text_lower or "repeat that" in text_lower:
            return "repeat_assistant"

        return None

    def _handle_voice_command(self, command: str):
        """Execute a voice command."""
        if command == "clear":
            self.memory.clear()
            speak_simple("Starting fresh. What's on your mind?", self.tts_enabled)

        elif command == "forget":
            self.memory.forget_last()
            speak_simple("Done. That exchange is forgotten.", self.tts_enabled)

        elif command == "repeat_user":
            if self.memory.turns:
                # Find last user message
                for turn in reversed(self.memory.turns):
                    if turn["role"] == "user":
                        speak_simple(f"You asked: {turn['content']}", self.tts_enabled)
                        return
            speak_simple("I don't have any previous questions.", self.tts_enabled)

        elif command == "repeat_assistant":
            if self.memory.turns:
                for turn in reversed(self.memory.turns):
                    if turn["role"] == "assistant":
                        speak_simple(turn["content"], self.tts_enabled)
                        return
            speak_simple("I haven't said anything yet.", self.tts_enabled)

    # --- Main Conversation Turn ---

    def _handle_turn(self, text: str):
        """Process one conversation turn: text → LLM → streaming TTS."""
        # Add user message to memory
        self.memory.add_user(text)

        # Build messages for Ollama
        messages = self.memory.get_messages()

        # Run the streaming pipeline
        log.info("Starting streaming pipeline...")
        response = self.pipeline.run(messages)

        # Check if the LLM decided to route to a specialist agent
        route_match = re.match(r"\[ROUTE:([\w-]+)\]\s*(.*)", response, re.DOTALL)
        if route_match:
            agent_id = route_match.group(1)
            refined_query = route_match.group(2).strip() or text
            self._handle_routing(agent_id, refined_query, text)
            return

        # Normal response — add to memory
        if response and not response.startswith("[error:"):
            self.memory.add_assistant(response)
            self._log_command(text, None, response)
        else:
            # Error occurred — don't add error messages to memory
            self._log_command(text, None, response or "no_response")

    def _handle_routing(self, agent_id: str, refined_query: str, original_text: str):
        """Handle smart routing to a specialist agent."""
        log.info(f"Routing to {agent_id}: {refined_query}")

        # Speak bridge phrase
        bridge = get_bridge_phrase(agent_id)
        speak_simple(bridge, self.tts_enabled)

        # Call agent
        self._set_state(State.PROCESSING)
        agent_response = send_to_agent(agent_id, refined_query)

        if agent_response:
            # Format and speak the agent response
            spoken = format_for_speech(agent_response)

            # Truncate long responses
            words = spoken.split()
            if len(words) > 150:
                spoken = " ".join(words[:150]) + ". Full response sent to Telegram."

            self._set_state(State.SPEAKING)
            speak_simple(spoken, self.tts_enabled)

            # Add to memory
            memory_text = f"[Routed to {AGENT_NAMES.get(agent_id, agent_id)}] {spoken}"
            self.memory.add_assistant(memory_text)
            self._log_command(original_text, agent_id, spoken)
        else:
            error_msg = f"The {AGENT_NAMES.get(agent_id, agent_id)} didn't respond."
            speak_simple(error_msg, self.tts_enabled)
            self._log_command(original_text, agent_id, "no_response")

    def _log_command(self, transcription: str, agent_id: Optional[str], response_summary: str):
        """Write to the command log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "transcription": transcription,
            "agentId": agent_id,
            "mode": "conversational",
            "responseSummary": response_summary[:500],
        }
        try:
            COMMAND_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(COMMAND_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.error(f"Failed to write command log: {e}")

    # --- Main Loop ---

    def run(self):
        """Main daemon loop with push-to-talk."""
        log.info("=" * 50)
        log.info("Jarvis Conversational Voice Agent starting...")
        log.info(f"  LLM: {LLM_MODEL} @ {LLM_BASE_URL}")
        log.info(f"  TTS: {'enabled' if self.tts_enabled else 'disabled'}")
        log.info(f"  VAD: {'webrtcvad' if HAS_VAD else 'energy-based'}")
        log.info(f"  Whisper: {'ready' if HAS_WHISPER else 'NOT AVAILABLE'}")
        log.info(f"  Piper: {'ready' if HAS_PIPER else f'fallback to {TTS_FALLBACK}'}")
        log.info(f"  Pynput: {'ready' if HAS_PYNPUT else 'NOT AVAILABLE'}")
        if CLOUD_FALLBACKS:
            fallback_names = [f["name"] for f in CLOUD_FALLBACKS]
            log.info(f"  Cloud fallbacks: {' → '.join(fallback_names)}")
        else:
            log.info("  Cloud fallbacks: none (llm-providers.json not found)")
        log.info(f"  Conversation memory: {len(self.memory.turns)} turns loaded")
        log.info("=" * 50)

        if not HAS_WHISPER:
            log.error("Cannot start without Whisper. Install with: pip install mlx-whisper")
            return

        # Set up hotkey
        listener = self._setup_hotkey()
        if not listener:
            log.error("Cannot start without pynput. Install with: pip install pynput")
            return

        log.info("")
        log.info("Ready. Press Cmd+Shift+J to talk. (Ctrl+C to stop)")
        log.info("")

        speak_simple("Jarvis online.", self.tts_enabled)

        while self.running:
            try:
                # Wait for PTT activation
                self._ptt_event.wait(timeout=1.0)
                if not self.running:
                    break
                if not self._ptt_event.is_set():
                    continue
                self._ptt_event.clear()

                # --- RECORDING ---
                self._set_state(State.RECORDING)
                play_beep(BEEP_FREQ, BEEP_DURATION)
                log.info("Recording... (speak now)")

                audio = self.listen_for_speech()

                play_beep(DEACTIVATION_FREQ, DEACTIVATION_DURATION)

                if audio is None:
                    log.info("No speech detected")
                    self._set_state(State.IDLE)
                    continue

                # --- PROCESSING ---
                self._set_state(State.PROCESSING)
                text = self.transcribe(audio)

                if not text:
                    speak_simple("I didn't catch that.", self.tts_enabled)
                    self._set_state(State.IDLE)
                    continue

                log.info(f"User said: {text}")

                # Check for voice commands
                voice_cmd = self._check_voice_command(text)
                if voice_cmd:
                    self._handle_voice_command(voice_cmd)
                    self._set_state(State.IDLE)
                    continue

                # --- SPEAKING (streaming) ---
                self._set_state(State.SPEAKING)
                self._handle_turn(text)
                self._set_state(State.IDLE)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Unexpected error: {e}", exc_info=True)
                self._set_state(State.IDLE)
                time.sleep(0.5)

        log.info("Jarvis shutting down.")
        speak_simple("Jarvis offline.", self.tts_enabled)


# ============================================================
# Test Modes
# ============================================================

def test_pipeline(text: str, tts_enabled: bool = True):
    """Test the streaming pipeline without microphone input."""
    log.info(f"Testing pipeline with: {text}")
    memory = ConversationMemory()
    memory.add_user(text)
    messages = memory.get_messages()

    pipeline = StreamingPipeline(tts_enabled=tts_enabled)
    response = pipeline.run(messages)
    print(f"\n[Full response]: {response}")

    # Check for routing
    route_match = re.match(r"\s*\[ROUTE:([\w-]+)\]\s*(.*)", response, re.DOTALL)
    if route_match:
        agent_id = route_match.group(1)
        query = route_match.group(2).strip() or text
        print(f"\n[Route detected]: {agent_id}")
        print(f"[Refined query]: {query}")
        bridge = get_bridge_phrase(agent_id)
        speak_simple(bridge, tts_enabled)
        agent_response = send_to_agent(agent_id, query)
        if agent_response:
            spoken = format_for_speech(agent_response)
            print(f"\n[Agent response]: {spoken}")
            speak_simple(spoken, tts_enabled)


def test_hotkey():
    """Test that the hotkey registers correctly."""
    if not HAS_PYNPUT:
        print("ERROR: pynput not installed. Run: pip install pynput")
        return

    print("Hotkey test mode.")
    print("Press Cmd+Shift+J — you should hear a beep and see a message.")
    print("Press Ctrl+C to exit.\n")

    event = threading.Event()

    pressed_keys = set()

    def on_press(key):
        try:
            pressed_keys.add(key)
            is_cmd = any(k in pressed_keys for k in (
                keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r
            ))
            is_shift = any(k in pressed_keys for k in (
                keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r
            ))
            is_j = hasattr(key, "char") and key.char and key.char.lower() == "j"

            if is_cmd and is_shift and is_j:
                print("Hotkey detected! Cmd+Shift+J pressed.")
                play_beep()
        except AttributeError:
            pass

    def on_release(key):
        try:
            pressed_keys.discard(key)
        except (AttributeError, KeyError):
            pass

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\nHotkey test complete.")


# ============================================================
# Entry Point
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Jarvis Conversational Voice Agent")
    parser.add_argument("--test-pipeline", metavar="TEXT",
                        help="Test streaming pipeline with given text (bypasses mic)")
    parser.add_argument("--test-hotkey", action="store_true",
                        help="Test Cmd+Shift+J hotkey registration")
    parser.add_argument("--no-tts", action="store_true",
                        help="Disable TTS (text output only)")
    parser.add_argument("--gateway", default=GATEWAY_URL,
                        help="OpenClaw gateway URL")
    args = parser.parse_args()

    tts_enabled = not args.no_tts

    if args.test_hotkey:
        test_hotkey()
        return

    if args.test_pipeline:
        test_pipeline(args.test_pipeline, tts_enabled)
        return

    # Normal mode — full conversational agent
    jarvis = JarvisVoice(tts_enabled=tts_enabled, gateway_url=args.gateway)
    jarvis.run()


if __name__ == "__main__":
    main()
