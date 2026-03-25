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

_FLITE_SUPPORTED_VOICES = {"slt", "rms", "awb"}

_ESPEAK_VOICES = {
    "female": "en+f3",
    "male": "en+m3",
}

_ESPEAK_SUPPORTED_VOICES = {
    "en+f3",
    "en+f4",
    "en+m3",
    "en+m7",
    "hi",
    "hi+f3",
}

_GTTS_SUPPORTED_TLDS = {
    "co.in",
    "com",
    "co.uk",
    "com.au",
}

_FLITE_DURATION_STRETCH = os.getenv("RK_FLITE_DURATION_STRETCH", "1.12").strip() or "1.12"
_ESPEAK_SPEED = os.getenv("RK_ESPEAK_SPEED", "145").strip() or "145"


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


def _normalize_language(language: str | None, text: str, engine: str | None = None) -> str:
    language_name = str(language or "").strip().lower()
    if engine == "gtts":
        return "hi"
    if language_name in {"hi", "hindi"}:
        return "hi"
    if language_name in {"en", "english"}:
        return "en"
    return "hi" if contains_hindi(text) else "en"


def _normalize_flite_voice(gender: str, voice: str | None = None) -> str:
    voice_name = str(voice or "").strip().lower()
    if voice_name in _FLITE_SUPPORTED_VOICES:
        return voice_name
    return _FLITE_VOICES[_normalize_gender(gender)]


def _normalize_espeak_voice(gender: str, voice: str | None = None, language: str | None = None) -> str:
    language_name = _normalize_language(language, "", engine="espeak")
    voice_name = str(voice or "").strip().lower()
    if language_name == "hi":
        if voice_name in {"hi", "hi+f3"}:
            return voice_name
        return "hi+f3" if _normalize_gender(gender) == "female" else "hi"
    if voice_name in _ESPEAK_SUPPORTED_VOICES and not voice_name.startswith("hi"):
        return voice_name
    return _ESPEAK_VOICES[_normalize_gender(gender)]


def _normalize_gtts_tld(voice: str | None = None) -> str:
    tld = str(voice or "").strip().lower()
    if tld in _GTTS_SUPPORTED_TLDS:
        return tld
    return "co.in"


def _gtts_mp3_path(text: str, language: str, tld: str) -> str:
    cache_key = hashlib.md5(f"{language}:{tld}:{text}".encode("utf-8")).hexdigest()
    return os.path.join(tempfile.gettempdir(), f"rk_tts_{cache_key}.mp3")


def _speak_with_flite(text: str, gender: str, voice: str | None = None) -> bool:
    spoken_text = fix_text(text)
    if not spoken_text:
        return True
    voice_name = _normalize_flite_voice(gender, voice)
    slower_cmd = (
        f"flite -voice {shlex.quote(voice_name)} "
        f"-set duration_stretch={shlex.quote(_FLITE_DURATION_STRETCH)} "
        f"-t {shlex.quote(spoken_text)}"
    )
    if _run_command(slower_cmd):
        return True
    cmd = f"flite -voice {shlex.quote(voice_name)} -t {shlex.quote(spoken_text)}"
    return _run_command(cmd)


def _speak_with_gtts(
    text: str,
    language: str | None = None,
    voice: str | None = None,
    allow_network: bool = True,
) -> bool:
    try:
        from gtts import gTTS
    except Exception:
        return False

    language_name = _normalize_language(language, text, engine="gtts")
    tld = _normalize_gtts_tld(voice)
    mp3_path = _gtts_mp3_path(text, language_name, tld)

    try:
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
            return _run_command(
                f"mpg123 -o pulse -b 8192 --no-resync -q {shlex.quote(mp3_path)}"
            )
        if not allow_network:
            return False
        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
            tts = gTTS(text=text, lang=language_name, tld=tld, slow=False)
            tts.save(mp3_path)
    except Exception:
        return False

    return _run_command(
        f"mpg123 -o pulse -b 8192 --no-resync -q {shlex.quote(mp3_path)}"
    )


def _speak_with_espeak(
    text: str,
    gender: str,
    voice: str | None = None,
    language: str | None = None,
) -> bool:
    voice_name = _normalize_espeak_voice(gender, voice, language or ("hi" if contains_hindi(text) else "en"))
    cmd = f"espeak-ng -s {shlex.quote(_ESPEAK_SPEED)} -v {shlex.quote(voice_name)} {shlex.quote(text)}"
    if _run_command(cmd):
        return True
    legacy_cmd = f"espeak -s {shlex.quote(_ESPEAK_SPEED)} -v {shlex.quote(voice_name)} {shlex.quote(text)}"
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
    voice: str | None = None,
    language: str | None = None,
    allow_gtts: bool = True,
    allow_network_gtts: bool = True,
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
            if engine_name == "flite" and _speak_with_flite(raw_text, gender_name, voice=voice):
                return
            if engine_name == "gtts" and _speak_with_gtts(
                raw_text,
                language=language,
                voice=voice,
                allow_network=allow_network_gtts,
            ):
                return
            if engine_name == "espeak" and _speak_with_espeak(
                raw_text,
                gender_name,
                voice=voice,
                language=language,
            ):
                return
        except Exception:
            continue


def speak(
    text: str,
    engine: str = "auto",
    gender: str = "female",
    voice: str | None = None,
    language: str | None = None,
) -> None:
    """
    Public TTS entry point.

    - Default: Flite.
    - Hindi text: gTTS.
    - Fallbacks: Flite -> gTTS -> espeak-ng.
    """
    try:
        speak_with_options(
            text=text,
            engine=engine,
            gender=gender,
            voice=voice,
            language=language,
            allow_gtts=True,
            allow_network_gtts=True,
        )
    except Exception:
        try:
            _speak_with_espeak(str(text or ""), gender, voice=voice, language=language)
        except Exception:
            pass
