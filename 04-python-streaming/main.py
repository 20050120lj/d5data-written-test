"""
FastAPI streaming demo.

Three endpoints that together show what "streaming" actually buys you:

    POST /api/chat/stream    SSE token stream (the interesting one)
    POST /api/chat           the same answer, buffered, as a baseline
    GET  /api/stats          per-request timing recorded by the server

Plus a browser demo at `/` that renders both paths side by side so the difference
is visible rather than argued about.

Why SSE and not `StreamingResponse` over chunked JSON: SSE is what LLM providers
actually emit, it survives proxies that buffer `application/json`, and browsers
consume it with `EventSource` without any client library.

Run:
    uvicorn main:app --reload --port 8000
    open http://127.0.0.1:8000/
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="FastAPI streaming demo",
    description="SSE token streaming vs. buffered responses, with cancellation and heartbeat.",
    version="1.0.0",
)

STATIC = Path(__file__).parent / "static"


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #

class ChatRequest(BaseModel):
    prompt: str = Field(default="用一句话解释什么是流式接口", max_length=2000)
    # Artificial per-token delay so the demo is observable. Set to 0 to measure raw overhead.
    token_delay_ms: int = Field(default=35, ge=0, le=500)
    max_tokens: int = Field(default=40, ge=1, le=400)
    # 1 in N requests simulates a mid-stream failure, to prove the client sees it.
    fail_rate: int = Field(default=0, ge=0, le=10)


class Stats:
    """Tiny in-process metrics store; enough to compare streamed vs buffered."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def record(self, **kw) -> None:
        kw["ts"] = time.time()
        self.requests.append(kw)
        del self.requests[:-200]  # keep the last 200

    def summary(self) -> dict:
        if not self.requests:
            return {"n": 0}
        by_mode: dict[str, list[dict]] = {}
        for r in self.requests:
            by_mode.setdefault(r["mode"], []).append(r)

        def agg(rows: list[dict]) -> dict:
            first = [r["first_byte_ms"] for r in rows]
            total = [r["total_ms"] for r in rows]
            return {
                "n": len(rows),
                "ttfb_ms_avg": round(sum(first) / len(first), 1),
                "total_ms_avg": round(sum(total) / len(total), 1),
                "cancelled": sum(1 for r in rows if r.get("cancelled")),
            }

        return {mode: agg(rows) for mode, rows in by_mode.items()}


stats = Stats()


# --------------------------------------------------------------------------- #
# Fake model
# --------------------------------------------------------------------------- #
# Deterministic sentence bank so the demo does not need an API key. The shape of
# the stream (token-by-token, with a first-token delay) is what matters here, not
# the text quality.

_CORPUS = (
    "流式接口的核心价值是把等待从一次长阻塞拆成很多次短等待，"
    "让首字节时间从秒级降到毫秒级。用户在看到第一个字之后才开始感知延迟，"
    "所以 TTFT 比总耗时更能决定体验。工程上还要处理心跳、断线重连、"
    "背压和取消传播这几件事，否则长连接会在网关处被静默切断。"
)


def _tokens(text: str, limit: int) -> list[str]:
    """Crude tokenizer: Chinese char-by-char, ASCII word-by-word."""
    out, buf = [], ""
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in "-_"):
            buf += ch
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
    if buf:
        out.append(buf)
    return out[:limit]


def _sse(event: str, data: dict) -> str:
    """SSE wire format. `event:` is optional but lets the client switch on type."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------- #
# Streaming endpoint
# --------------------------------------------------------------------------- #

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """SSE token stream.

    Four things a production stream needs and a toy demo usually omits:

    1. **Immediate first byte.** A `start` event is flushed before any model work,
       so the client's spinner stops and the connection is provably open.
    2. **Heartbeat.** Comments (`: ping`) every few seconds keep idle-timeout
       proxies from killing a long generation.
    3. **Cancellation.** `request.is_disconnected()` is checked every token; when
       the client goes away the generator stops instead of burning compute.
    4. **Typed terminal event.** `done` carries usage, and `error` is a normal
       event, not an HTTP 500 in the middle of a 200 response (which clients can't
       see once headers are sent).
    """
    started = time.perf_counter()
    first_byte_ms: float | None = None
    cancelled = False

    async def gen() -> AsyncIterator[str]:
        nonlocal first_byte_ms, cancelled

        try:
            yield _sse("start", {"id": f"cmpl-{random.randint(1000, 9999)}", "model": "demo-1"})
            first_byte_ms = (time.perf_counter() - started) * 1000

            toks = _tokens(_CORPUS * 2, req.max_tokens)
            emitted = 0
            for i, tok in enumerate(toks):
                if await request.is_disconnected():
                    cancelled = True
                    break
                if req.fail_rate and random.randint(1, req.fail_rate) == 1:
                    yield _sse("error", {"message": "simulated upstream failure", "at_token": i})
                    break
                await asyncio.sleep(req.token_delay_ms / 1000)
                yield _sse("token", {"text": tok, "index": i})
                emitted += 1
                # Heartbeat every 50 tokens keeps idle connections alive.
                if i and i % 50 == 0:
                    yield ": ping\n\n"

            yield _sse(
                "done",
                {
                    "tokens": emitted,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "cancelled": cancelled,
                },
            )
        except asyncio.CancelledError:
            # Starlette cancels the generator when the peer goes away; the flag has
            # to be set here too, otherwise a cancelled stream looks like a normal
            # short one in the metrics.
            cancelled = True
            raise
        finally:
            # `finally` (not the happy path) is where accounting belongs: a stream
            # that raised or was cancelled must still be counted.
            stats.record(
                mode="stream",
                first_byte_ms=first_byte_ms or 0.0,
                total_ms=(time.perf_counter() - started) * 1000,
                cancelled=cancelled,
            )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Tell nginx not to buffer: without this the whole point is lost.
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Buffered baseline
# --------------------------------------------------------------------------- #

@app.post("/api/chat")
async def chat_buffered(req: ChatRequest) -> JSONResponse:
    """The same answer computed to completion before any byte is sent."""
    started = time.perf_counter()
    toks = _tokens(_CORPUS * 2, req.max_tokens)
    await asyncio.sleep(req.token_delay_ms * len(toks) / 1000)
    body = {"text": "".join(toks), "tokens": len(toks)}
    total_ms = (time.perf_counter() - started) * 1000
    stats.record(mode="buffered", first_byte_ms=total_ms, total_ms=total_ms, cancelled=False)
    return JSONResponse(body)


# --------------------------------------------------------------------------- #
# Plain generator stream (no SSE) — for comparison / teaching
# --------------------------------------------------------------------------- #

@app.get("/api/count")
async def count(n: int = 20) -> StreamingResponse:
    """Minimal `yield` demo: newline-delimited numbers, one chunk per tick."""

    async def gen() -> AsyncIterator[str]:
        for i in range(n):
            yield f"{i}\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/plain")


@app.get("/api/stats")
async def get_stats() -> dict:
    return stats.summary()


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")
