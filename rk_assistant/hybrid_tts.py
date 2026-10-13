"""
Hybrid TTS for low-power Raspberry Pi devices.

Priority:
1. Flite for offline English speech.
2. gTTS for Hindi or when Flite fails.
3. espeak-ng as the final safety net.
"""

from __future__ import annotations

import hashlib
import logging
import os
import queue
import re
import shlex
import tempfile
import threading

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistent HTTP session for gTTS — avoids TLS handshake on every call.
# The Pi Zero W's slow ARMv6 CPU makes TLS very expensive (~1-3s per call).
# By reusing one session, we pay the handshake cost only once per process.
# ---------------------------------------------------------------------------
try:
    import requests as _requests

    _gtts_session = _requests.Session()
    _gtts_session.headers.update({"Connection": "keep-alive"})

    # Monkey-patch gTTS to use our persistent session so keep-alive works.
    try:
        import gtts.tts as _gtts_mod  # noqa: PLC0415
        _gtts_mod.requests = _gtts_session  # type: ignore[attr-defined]
    except Exception:
        pass  # non-critical; gTTS will still work, just without keep-alive
except Exception:
    _gtts_session = None  # type: ignore[assignment]


def _warm_dns() -> None:
    """Pre-resolve Google TTS hostname so the first speak() call skips DNS."""
    import socket  # noqa: PLC0415
    try:
        socket.getaddrinfo("translate.google.com", 443)
        socket.getaddrinfo("translate.google.co.in", 443)
        _log.debug("[tts] DNS pre-warm done")
    except Exception:
        pass


threading.Thread(target=_warm_dns, daemon=True, name="gtts-dns-warm").start()

# ---------------------------------------------------------------------------
# Background gTTS prefetch worker
# ---------------------------------------------------------------------------
_prefetch_queue: queue.Queue = queue.Queue()
_prefetch_lock = threading.Lock()          # prevents duplicate in-flight fetches
_prefetch_in_flight: set[str] = set()     # tracks mp3 paths currently being fetched


def _gtts_prefetch_worker() -> None:
    """Long-lived daemon thread that fetches gTTS MP3s in the background."""
    while True:
        try:
            mp3_path, text, language_name, tld = _prefetch_queue.get(timeout=60)
        except queue.Empty:
            continue
        try:
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                continue  # already cached by the time we got here
            from gtts import gTTS  # noqa: PLC0415
            tts = gTTS(text=text, lang=language_name, tld=tld, slow=False)
            tmp = mp3_path + ".tmp"
            tts.save(tmp)
            os.replace(tmp, mp3_path)   # atomic rename
            _log.debug("[tts-cache] cached '%s' → %s", text[:60], mp3_path)
        except Exception as exc:
            _log.debug("[tts-cache] prefetch failed for '%s': %s", text[:60], exc)
        finally:
            with _prefetch_lock:
                _prefetch_in_flight.discard(mp3_path)
            _prefetch_queue.task_done()


_prefetch_thread = threading.Thread(
    target=_gtts_prefetch_worker, daemon=True, name="gtts-prefetch"
)
_prefetch_thread.start()


def _enqueue_gtts_prefetch(mp3_path: str, text: str, language_name: str, tld: str) -> None:
    """Add a gTTS fetch job to the background queue (skips duplicates)."""
    with _prefetch_lock:
        if mp3_path in _prefetch_in_flight:
            return
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
            return  # already cached
        _prefetch_in_flight.add(mp3_path)
    _prefetch_queue.put_nowait((mp3_path, text, language_name, tld))


def prefetch_phrases(
    phrases: list[str],
    language: str = "en",
    voice: str | None = None,
) -> None:
    """
    Warm the gTTS cache for a list of phrases in the background.
    Call this at startup with common fixed phrases so first-use is instant.
    """
    tld = _normalize_gtts_tld(voice)
    for phrase in phrases:
        if not phrase:
            continue
        lang = _normalize_language(language, phrase, engine="gtts")
        mp3_path = _gtts_mp3_path(phrase, lang, tld)
        _enqueue_gtts_prefetch(mp3_path, phrase, lang, tld)


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


def _get_mpg123_args() -> str:
    """Return volume-scaled mpg123 flags as a string fragment."""
    try:
        from .audio_utils import get_current_volume  # noqa: PLC0415
        vol_pct = get_current_volume()
    except Exception:
        vol_pct = 50
    gain = int(32768 * max(0, min(100, vol_pct)) / 100)
    return f"-f {gain} -b 8192 --no-resync -q"


def _play_mp3(mp3_path: str) -> bool:
    """Play a cached MP3 via mpg123, volume-synced to the app's current level."""
    quoted = shlex.quote(mp3_path)
    flags = _get_mpg123_args()
    # 1. Try pulse output
    if _run_command(f"mpg123 -o pulse {flags} {quoted}"):
        return True
    # 2. Try alsa output
    if _run_command(f"mpg123 -o alsa {flags} {quoted}"):
        return True
    # 3. Default mpg123
    return _run_command(f"mpg123 {flags} {quoted}")


def _stream_gtts_to_mpg123(
    tts,  # gTTS instance
    mp3_path: str,
) -> bool:
    """
    Stream gTTS bytes directly into mpg123 stdin — playback starts on the
    first chunk, no full download wait.  Simultaneously writes to mp3_path
    so the next call hits the cache.
    """
    import subprocess as _sp  # noqa: PLC0415
    import io  # noqa: PLC0415

    flags = _get_mpg123_args().split()

    for output_flags in (["-o", "pulse"], ["-o", "alsa"], []):
        try:
            cmd = ["mpg123"] + output_flags + flags + ["-"]
            proc = _sp.Popen(cmd, stdin=_sp.PIPE, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            buf = io.BytesIO()

            class _Tee:
                """Tee: feeds mpg123 stdin and accumulates cache bytes."""
                def __init__(self, _p, _b):
                    self._p = _p
                    self._b = _b

                def write(self, data: bytes) -> None:
                    self._p.stdin.write(data)
                    self._b.write(data)

            tts.write_to_fp(_Tee(proc, buf))
            proc.stdin.close()
            proc.wait()

            # Atomically cache the full MP3 for instant playback next time
            mp3_data = buf.getvalue()
            if mp3_data:
                tmp = mp3_path + ".tmp"
                try:
                    with open(tmp, "wb") as f:
                        f.write(mp3_data)
                    os.replace(tmp, mp3_path)
                    _log.debug("[tts-cache] saved '%s'", mp3_path)
                except Exception:
                    pass  # cache write failure is non-fatal

            return proc.returncode == 0
        except Exception:
            continue
    return False


def _speak_with_gtts(
    text: str,
    language: str | None = None,
    voice: str | None = None,
    allow_network: bool = True,
    gender: str = "female",
) -> bool:
    """
    Play speech via gTTS (Google TTS) — always.

    Cache HIT  → play the cached MP3 instantly (zero network wait).
    Cache MISS → STREAM from Google → mpg123 stdin so playback begins on
                 the first arriving chunk — no full download wait.
                 The MP3 is also cached to disk for the next call.
    """
    try:
        from gtts import gTTS  # noqa: PLC0415
    except Exception:
        return False

    language_name = _normalize_language(language, text, engine="gtts")
    tld = _normalize_gtts_tld(voice)
    mp3_path = _gtts_mp3_path(text, language_name, tld)

    # ── Cache HIT: play instantly ────────────────────────────────────────────
    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
        return _play_mp3(mp3_path)

    # ── Cache MISS: stream to mpg123 directly ──────────────────────────────
    if not allow_network:
        return False

    try:
        tts = gTTS(text=text, lang=language_name, tld=tld, slow=False)
        return _stream_gtts_to_mpg123(tts, mp3_path)
    except Exception as exc:
        _log.debug("[tts] gTTS stream failed for '%s': %s", text[:60], exc)
        return False



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
                gender=gender_name,
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
