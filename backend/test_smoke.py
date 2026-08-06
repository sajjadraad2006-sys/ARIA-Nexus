"""
Smoke + light unit tests for the ARIA Nexus backend.

Verifies that the Flask app factory builds, that the launcher health endpoint
responds, and that the Phase 1-5 building blocks (warm Piper pool, multilingual
Whisper config, VAD/wake config, Arabic detection) are wired correctly.

Heavy ML deps (torch, chromadb, llama, ...) may not be installed in every
environment, so tests self-skip if server.py cannot be imported rather than
failing the whole suite.

Runs either way:
    cd backend && python -m pytest -q       # if pytest is installed
    cd backend && python test_smoke.py      # standalone fallback runner
"""
import os

# Importing the app must never require a real secret.
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

try:
    import pytest
except Exception:  # pragma: no cover - standalone mode
    pytest = None


class _Skip(Exception):
    pass


def _skip(msg):
    if pytest is not None:
        pytest.skip(msg)
    raise _Skip(msg)


def _load_app():
    try:
        from server import create_app
    except Exception as exc:  # missing optional deps in this environment
        _skip(f"server import unavailable: {exc}")
    return create_app()


# --------------------------------------------------------------------------
# App factory + routes
# --------------------------------------------------------------------------
def test_app_factory_builds():
    app, socketio = _load_app()
    assert app is not None
    assert socketio is not None
    # The secret must come from env / random - never the old hard-coded value.
    assert app.config["SECRET_KEY"] != "smart-robot-delivery-secret"


def test_health_route_responds():
    app, _ = _load_app()
    client = app.test_client()
    resp = client.get("/api/launcher/health")
    assert resp.status_code == 200


def test_config_route_exposes_vad_and_wake():
    """Phase 3/4: the frontend tunables route must return VAD + wake blocks."""
    app, _ = _load_app()
    client = app.test_client()
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("ok") is True
    assert isinstance(data.get("vad"), dict)
    assert isinstance(data.get("wake"), dict)


# --------------------------------------------------------------------------
# config.py - multilingual Whisper + Piper + VAD/wake knobs
# --------------------------------------------------------------------------
def test_config_has_multilingual_and_voice_keys():
    try:
        import config as cfg
    except Exception as exc:
        _skip(f"config import unavailable: {exc}")
    # Multilingual STT (Phase 2)
    assert hasattr(cfg, "WHISPER_LANGUAGE")
    assert hasattr(cfg, "WHISPER_MODEL_FILE")
    # Warm Piper voices (Phase 1)
    assert hasattr(cfg, "PIPER_DEFAULT_VOICE")
    assert hasattr(cfg, "PIPER_ARABIC_VOICE")
    assert hasattr(cfg, "PIPER_PREWARM_VOICES")
    # VAD + wake tunables (Phase 3/4)
    assert isinstance(getattr(cfg, "VAD_CONFIG", None), dict)
    assert hasattr(cfg, "WAKE_THRESHOLD")
    assert hasattr(cfg, "WAKE_TRIGGER_FRAMES")
    # Wake threshold should be a sane, non-trivial value (the old 0.1 was the
    # root cause of false-accepts).
    assert 0.0 < float(cfg.WAKE_THRESHOLD) <= 1.0



def test_local_service_urls_are_valid():
    """Local service URLs must be valid HTTP URLs without stray braces."""
    try:
        import config as cfg
    except Exception as exc:
        _skip(f"config import unavailable: {exc}")

    from urllib.parse import urlparse

    for name in ("WHISPER_URL", "LLAMA_URL", "TTS_URL"):
        value = getattr(cfg, name)
        parsed = urlparse(value)

        assert "{" not in value and "}" not in value, (
            f"{name} contains invalid braces: {value}"
        )
        assert parsed.scheme == "http", (
            f"{name} must use http: {value}"
        )
        assert parsed.hostname == "127.0.0.1", (
            f"{name} must remain local: {value}"
        )
        assert parsed.port is not None, (
            f"{name} must include a port: {value}"
        )

# --------------------------------------------------------------------------
# piper_tts pool - graceful degradation when Piper/models are absent
# --------------------------------------------------------------------------
def test_piper_pool_degrades_gracefully():
    try:
        from piper_tts import get_pool, PiperVoicePool, PiperUnavailable
    except Exception as exc:
        _skip(f"piper_tts import unavailable: {exc}")
    # The pool MUST import and construct even with no piper package / no voice
    # files (so the module never breaks server import).
    pool = get_pool()
    # Introspection helpers must never raise regardless of availability.
    assert isinstance(pool.is_available(), bool)
    assert isinstance(pool.reason(), str)
    assert isinstance(pool.loaded_voices(), (list, tuple))
    # Contract: when Piper/models are absent, synthesize raises PiperUnavailable
    # so callers (server.generate_piper_audio) can catch it and fall back to the
    # legacy subprocess path. Empty text is a no-op (returns None) either way.
    assert pool.synthesize("", None) is None
    if not pool.is_available():
        try:
            pool.synthesize("hello", None)
        except PiperUnavailable:
            pass
        else:
            raise AssertionError("expected PiperUnavailable when pool unavailable")


# --------------------------------------------------------------------------
# Arabic detection used for auto voice-switching
# --------------------------------------------------------------------------
def test_arabic_detection():
    try:
        from server import _is_arabic_text
    except Exception as exc:
        _skip(f"server import unavailable: {exc}")
    assert _is_arabic_text("مرحبا كيف حالك") is True
    assert _is_arabic_text("hello how are you") is False


# --------------------------------------------------------------------------
# Standalone runner (no pytest required)
# --------------------------------------------------------------------------
def _run_standalone():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = skipped = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS  {t.__name__}")
        except _Skip as s:
            skipped += 1
            print(f"SKIP  {t.__name__}: {s}")
        except AssertionError as a:
            failed += 1
            print(f"FAIL  {t.__name__}: {a}")
        except Exception as e:  # unexpected
            failed += 1
            print(f"ERROR {t.__name__}: {e}")
    print(f"\n{passed} passed, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_standalone())
