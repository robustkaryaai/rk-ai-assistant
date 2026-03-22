"""
Hybrid TTS for low-power Raspberry Pi devices.

Priority:
1. Flite for offline English speech.
2. gTTS for Hindi or when Flite fails.
3. espeak-ng as the final safety net.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import tempfile


_HINDI_RE = re.compile(r"[\u0900-\u097F]")

_PHONETIC_FIXES = {
    "Radhe": "Ra-dhay",
    "Krishna": "Krish-na",
    "Namaste": "Na-mas-tay",
}

_FLITE_VOICES = {
    "female": "slt",
    "male": "rms",
}

_ESPEAK_VOICES = {
    "female": "en+f3",
    "male": "en+m3",
}


def contains_hindi(text: str) -> bool:
    """Return True when the text contains Devanagari characters."""
    return bool(_HINDI_RE.search(text or ""))


def fix_text(text: str) -> str:
    """Apply simple phonetic replacements for Flite pronunciation."""
    fixed = text or ""
    for source, target in _PHONETIC_FIXES.items():
        fixed = re.sub(rf"\b{re.escape(source)}\b", target, fixed, flags=re.IGNORECASE)
    return fixed.strip()


def _run_command(command: str) -> bool:
    """Run a shell command quietly and report success."""
    try:
        return os.system(f"{command} >/dev/null 2>&1") == 0
    except Exception:
        return False


def _normalize_gender(gender: str) -> str:
    return "male" if str(gender).strip().lower() == "male" else "female"


def _normalize_engine(engine: str) -> str:
    engine_name = str(engine or "auto").strip().lower()
    if engine_name in {"auto", "flite", "gtts", "espeak"}:
        return engine_name
    return "auto"


def _gtts_mp3_path(text: str, language: str) -> str:
    cache_key = hashlib.md5(f"{language}:{text}".encode("utf-8")).hexdigest()
    return os.path.join(tempfile.gettempdir(), f"rk_tts_{cache_key}.mp3")


def _speak_with_flite(text: str, gender: str) -> bool:
    spoken_text = fix_text(text)
    if not spoken_text:
        return True
    voice = _FLITE_VOICES[_normalize_gender(gender)]
    cmd = f"flite -voice {shlex.quote(voice)} -t {shlex.quote(spoken_text)}"
    return _run_command(cmd)


def _speak_with_gtts(text: str) -> bool:
    try:
        from gtts import gTTS
    except Exception:
        return False

    language = "hi" if contains_hindi(text) else "en"
    mp3_path = _gtts_mp3_path(text, language)

    try:
        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
            tts = gTTS(text=text, lang=language, slow=False)
            tts.save(mp3_path)
    except Exception:
        return False

    return _run_command(f"mpg123 -q {shlex.quote(mp3_path)}")


def _speak_with_espeak(text: str, gender: str) -> bool:
    if contains_hindi(text):
        voice = "hi"
    else:
        voice = _ESPEAK_VOICES[_normalize_gender(gender)]
    cmd = f"espeak-ng -s 160 -v {shlex.quote(voice)} {shlex.quote(text)}"
    if _run_command(cmd):
        return True
    legacy_cmd = f"espeak -s 160 -v {shlex.quote(voice)} {shlex.quote(text)}"
    return _run_command(legacy_cmd)


def _build_engine_chain(engine: str, text: str, allow_gtts: bool = True) -> list[str]:
    requested = _normalize_engine(engine)
    hindi = contains_hindi(text)

    if requested == "auto":
        chain = ["gtts", "espeak"] if hindi else ["flite", "gtts", "espeak"]
    elif requested == "flite":
        chain = ["flite", "gtts", "espeak"]
    elif requested == "gtts":
        chain = ["gtts", "espeak"]
    else:
        chain = ["espeak"]

    if allow_gtts:
        return chain
    return [item for item in chain if item != "gtts"] or ["espeak"]


def speak_with_options(
    text: str,
    engine: str = "auto",
    gender: str = "female",
    allow_gtts: bool = True,
) -> None:
    """
    Internal entry point used by the assistant wrapper.
    This keeps the public API small while allowing offline-only calls when needed.
    """
    raw_text = str(text or "").strip()
    if not raw_text:
        return

    gender_name = _normalize_gender(gender)
    for engine_name in _build_engine_chain(engine, raw_text, allow_gtts=allow_gtts):
        try:
            if engine_name == "flite" and _speak_with_flite(raw_text, gender_name):
                return
            if engine_name == "gtts" and _speak_with_gtts(raw_text):
                return
            if engine_name == "espeak" and _speak_with_espeak(raw_text, gender_name):
                return
        except Exception:
            continue


def speak(text: str, engine: str = "auto", gender: str = "female") -> None:
    """
    Public TTS entry point.

    - Default: Flite.
    - Hindi text: gTTS.
    - Fallbacks: Flite -> gTTS -> espeak-ng.
    """
    try:
        speak_with_options(text=text, engine=engine, gender=gender, allow_gtts=True)
    except Exception:
        try:
            _speak_with_espeak(str(text or ""), gender)
        except Exception:
            pass
