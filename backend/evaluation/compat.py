"""Python 3.14 + greenlet + httpcore + Ragas compatibility shims.

Moved verbatim (behaviour-wise) out of run_evaluation.py so they live in one place.
They MUST be imported before ragas / langchain / aiohttp:  `import evaluation.compat  # noqa`

WARNING: these shims replace asyncio.timeout with a no-op. Nothing in the eval process will time out
by itself, so a hung network call hangs the run (Ctrl+C it and re-run). Set EVAL_SKIP_COMPAT=1 to skip
them entirely (e.g. if you run the retrieval stage on a Python version that does not need them).
"""
import os
import sys
import types
import asyncio


def apply() -> None:
    dummy_nest = types.ModuleType("nest_asyncio")
    dummy_nest.apply = lambda *args, **kwargs: None
    sys.modules["nest_asyncio"] = dummy_nest

    import asyncio.timeouts as _asyncio_timeouts

    class _GreenletSafeTimeout:
        def __init__(self, when):
            self._when = when
            self._expired = False

        def when(self):
            return self._when

        def reschedule(self, when):
            self._when = when

        def expired(self):
            return self._expired

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    def _safe_timeout(delay):
        try:
            loop = asyncio._get_running_loop()
            when = (loop.time() + delay) if (delay is not None and loop is not None) else None
        except Exception:
            when = None
        return _GreenletSafeTimeout(when)

    def _safe_timeout_at(when):
        return _GreenletSafeTimeout(when)

    _asyncio_timeouts.Timeout = _GreenletSafeTimeout  # type: ignore
    _asyncio_timeouts.timeout = _safe_timeout  # type: ignore
    _asyncio_timeouts.timeout_at = _safe_timeout_at  # type: ignore
    asyncio.Timeout = _GreenletSafeTimeout  # type: ignore
    asyncio.timeout = _safe_timeout  # type: ignore
    asyncio.timeout_at = _safe_timeout_at  # type: ignore

    try:
        import aiohttp.helpers as _aiohttp_helpers
        import aiohttp.connector as _aiohttp_connector

        def _safe_ceil_timeout(delay, ceil_threshold=5):
            return _safe_timeout(delay)

        _aiohttp_helpers.ceil_timeout = _safe_ceil_timeout  # type: ignore
        _aiohttp_connector.ceil_timeout = _safe_ceil_timeout  # type: ignore
    except ImportError:
        pass

    try:
        import sniffio
        sniffio.current_async_library = lambda: "asyncio"
    except ImportError:
        pass

    try:
        import httpcore._synchronization as _hc_sync
        _hc_sync.current_async_library = lambda: "asyncio"
    except ImportError:
        pass

    try:
        import langchain_community.chat_models.vertexai  # type: ignore  # noqa: F401
    except ImportError:
        dummy_vertex = types.ModuleType("langchain_community.chat_models.vertexai")
        dummy_vertex.ChatVertexAI = type("ChatVertexAI", (object,), {})
        sys.modules["langchain_community.chat_models.vertexai"] = dummy_vertex


if os.environ.get("EVAL_SKIP_COMPAT") != "1":
    apply()
