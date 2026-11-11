# FastAPI streaming API demo

A minimal but production-shaped demo of token-level streaming with FastAPI, plus a browser page
that runs the streaming and buffered paths side by side so the difference is measured, not
asserted.

## Why SSE rather than `StreamingResponse` over chunked JSON

`StreamingResponse` alone just gives you a chunked body. SSE adds three things that matter for
LLM-style output: an event type per frame (`start` / `token` / `error` / `done`), a wire format
browsers can consume with `EventSource`, and — critically — a `text/event-stream` content type,
which is what makes proxies stop buffering. A chunked `application/json` body frequently gets
buffered by nginx and arrives all at once, which silently destroys the whole point.

## Endpoints

| Method | Path | What it shows |
| --- | --- | --- |
| `POST` | `/api/chat/stream` | SSE token stream. `start` is flushed **before** any generation work, tokens follow, `done` carries usage. |
| `POST` | `/api/chat` | Same answer, fully buffered. Baseline for the TTFB comparison. |
| `GET` | `/api/count` | Eight-line `yield` demo (plain newline-delimited stream) for contrast. |
| `GET` | `/api/stats` | Per-mode TTFB / total / cancellation counters. |
| `GET` | `/` | Browser demo: stream on the left, buffered on the right. |
| `GET` | `/health` | Liveness. |

## Run

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# then open http://127.0.0.1:8000/
```

Verify on the wire:

```bash
python test_stream.py --base http://127.0.0.1:8000
```

```
12/12 checks passed
  [PASS] first event is `start`
  [PASS] stream TTFB ≪ buffered total  — stream ttfb 4 ms vs buffered 1218 ms
  [PASS] client can abort mid-stream   — closed after 0.17s / 6 frames
  [PASS] server recorded the cancellation
  [PASS] 10 concurrent streams overlap — wall 0.68s vs serial 6.57s
  [PASS] error is delivered as an event
```

Manual check with curl (note `-N`, which disables curl's own buffering):

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"hi","token_delay_ms":50,"max_tokens":20}'
```

## The four things a stream actually needs

1. **First byte before work.** The `start` event is yielded before the first token is computed,
   so the client's spinner stops immediately and the connection is provably open. Measured TTFB
   is 4 ms vs 1218 ms for the buffered call on the same payload.
2. **Heartbeat.** `: ping` comments every 50 tokens. Comment lines are ignored by `EventSource`
   but keep idle-timeout proxies from killing a long generation.
3. **Cancellation propagation.** `request.is_disconnected()` is polled per token, **and**
   `asyncio.CancelledError` is caught — Starlette cancels the generator when the peer leaves, so
   without the second path an aborted stream is silently counted as a normal short one. This was
   a real bug found by `test_cancel`; the fix moved the accounting into `finally`.
4. **Typed terminal events.** `error` is an SSE event, not an HTTP 500: once headers are sent you
   cannot change the status code, so a mid-stream failure has to be in-band.

## Files

| File | Role |
| --- | --- |
| `main.py` | App: SSE generator, buffered baseline, tiny metrics store |
| `static/index.html` | Side-by-side browser demo (fetch + `ReadableStream` SSE parser, since `EventSource` cannot POST) |
| `test_stream.py` | Wire-level checks: protocol order, TTFB, cancellation, 10-way concurrency, in-band error |
| `requirements.txt` | fastapi, uvicorn[standard], httpx |

## Production checklist (not implemented here, on purpose)

- **Proxy config**: `proxy_buffering off;` in nginx, plus `X-Accel-Buffering: no` (already sent).
- **Backpressure**: an `asyncio.Queue(maxsize=N)` between producer and consumer, so a slow client
  cannot make the server buffer unboundedly.
- **Rate limiting / auth**: SSE connections are long-lived; standard per-request rate limits
  undercount them. Limit on concurrent connections.
- **Reconnect**: send `retry:` and a `Last-Event-ID`, and make the generator replayable.
- **Observability**: per-stage timings (queue wait / model first token / total), not just total.
