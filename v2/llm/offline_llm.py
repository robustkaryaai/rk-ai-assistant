"""
offline_llm.py — Local LLM fallback for RK AI Assistant V2
Uses llama.cpp (llama-cli) with Qwen2.5-0.5B Q4_K_M when internet is unavailable.

Model: Qwen2.5-0.5B-Instruct Q4_K_M
Size:  ~300MB (fits on Pi Zero W 512MB RAM)
Speed: ~8-15 tok/s on Pi Zero W (10-20s per response)
"""

import os
import subprocess
import shutil
import time
import logging

logger = logging.getLogger("OfflineLLM")

# ─────────────────────────────────────────────────────────────
# CONFIG — adjust paths for Pi vs Mac
# ─────────────────────────────────────────────────────────────
MODEL_PATH = os.environ.get(
    "RK_LLM_MODEL",
    os.path.expanduser("~/models/qwen.gguf")
)

LLAMA_CLI_CANDIDATES = [
    "/usr/local/bin/llama-cli",       # Pi (compiled from source)
    "/opt/homebrew/bin/llama-cli",    # Mac (brew)
    shutil.which("llama-cli") or "",
]

CTX_SIZE    = 512    # Keep low for Pi Zero W RAM
MAX_TOKENS  = 150    # Short focused answers
TEMPERATURE = 0.6
TOP_P       = 0.9
REPEAT_PEN  = 1.1
TIMEOUT_SEC = 90     # Pi Zero W is slow — give it time

# System prompt: keep it short and punchy for the Pi's tiny context
SYSTEM_PROMPT = (
    "You are RK AI, a smart offline assistant. "
    "Give short, direct, accurate answers. "
    "If you don't know something, say so honestly."
)


def _find_llama_cli() -> str | None:
    """Find llama-cli binary on this system."""
    for path in LLAMA_CLI_CANDIDATES:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


class OfflineLLM:
    """
    Offline LLM engine using llama.cpp.
    Drop-in fallback when RKHomeClient cannot reach the backend.
    """

    def __init__(self):
        self.llama_cli = _find_llama_cli()
        self.model_path = MODEL_PATH
        self._ready = False
        self._check_ready()

    def _check_ready(self):
        """Validate that binary and model are both present."""
        if not self.llama_cli:
            logger.warning("[OfflineLLM] llama-cli not found. Offline LLM disabled.")
            logger.warning("[OfflineLLM] Install: sudo apt install llama.cpp  OR  brew install llama.cpp")
            return
        if not os.path.isfile(self.model_path):
            logger.warning(f"[OfflineLLM] Model not found at {self.model_path}")
            logger.warning("[OfflineLLM] Run: python3 v2/llm/download_model.py")
            return
        size_mb = os.path.getsize(self.model_path) / 1024 / 1024
        logger.info(f"[OfflineLLM] ✅ Ready — {self.llama_cli} | model {size_mb:.0f}MB")
        self._ready = True

    @property
    def is_ready(self) -> bool:
        return self._ready

    def ask(self, user_text: str) -> str | None:
        """
        Run a single-turn inference.
        Returns the model's response string, or None on failure.
        """
        if not self._ready:
            logger.error("[OfflineLLM] Not ready — cannot run inference.")
            return None

        # Build ChatML-format prompt
        prompt = (
            f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
            f"<|im_start|>user\n{user_text}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        cmd = [
            self.llama_cli,
            "-m", self.model_path,
            "-p", prompt,
            "-n", str(MAX_TOKENS),
            "-c", str(CTX_SIZE),
            "--temp", str(TEMPERATURE),
            "--top-p", str(TOP_P),
            "--repeat-penalty", str(REPEAT_PEN),
            "--single-turn",
            "--log-disable",
        ]

        logger.info(f"[OfflineLLM] 🧠 Thinking locally: '{user_text[:50]}...'")
        start = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SEC
            )
            elapsed = time.time() - start

            # Extract just the assistant's reply from stdout
            output = result.stdout or ""
            # Strip the echoed prompt — find text after last <|im_start|>assistant
            if "<|im_start|>assistant" in output:
                output = output.split("<|im_start|>assistant")[-1]
            # Strip stop tokens and trailing junk
            for stop in ["<|im_end|>", "<|im_start|>", "[end of text]", "Exiting..."]:
                output = output.split(stop)[0]
            output = output.strip()

            logger.info(f"[OfflineLLM] ✅ Done in {elapsed:.1f}s — '{output[:60]}...'")
            return output if output else None

        except subprocess.TimeoutExpired:
            logger.error(f"[OfflineLLM] ❌ Timeout after {TIMEOUT_SEC}s")
            return None
        except Exception as e:
            logger.error(f"[OfflineLLM] ❌ Error: {e}")
            return None
