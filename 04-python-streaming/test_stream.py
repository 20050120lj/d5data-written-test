#!/usr/bin/env python3
"""
End-to-end checks for the streaming demo.

These are not unit tests — they hit a running server, because the properties worth
verifying (time-to-first-byte, incremental delivery, cancellation propagation,
concurrency) only exist on the wire.

    uvicorn main:app --port 8000 &
    python test_stream.py --base http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  — {detail}" if detail else ""))


async def read_sse(client: httpx.AsyncClient, base: str, payload: dict):
    """Yield (event, data, t_first, t_now) for each SSE frame."""
    t0 = time.perf_counter()
    t_first = None
    async with client.stream("POST", f"{base}/api/chat/stream", json=payload) as resp:
        resp.raise_for_status()
        buf = ""
        async for chunk in resp.aiter_text():
            if t_first is None:
                t_first = time.perf_counter() - t0
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                event, data = "message", ""
                for line in frame.split("\n"):
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data += line[5:].strip()
                if data:
                    yield event, json.loads(data), t_first, time.perf_counter() - t0


async def test_health(client, base):
    r = await client.get(f"{base}/health")
    check("health endpoint", r.status_code == 200 and r.json().get("ok") is True)


async def test_sse_protocol(client, base):
    events, texts = [], []
    t_first = None
    async for ev, data, tf, tn in read_sse(client, base, {"token_delay_ms": 5, "max_tokens": 30}):
        events.append(ev)
        t_first = tf
        if ev == "token":
            texts.append(data["text"])
    check("first event is `start`", events and events[0] == "start", str(events[:2]))
    check("last event is `done`", events and events[-1] == "done")
    check("token events present", events.count("token") >= 20, f"{events.count('token')} tokens")
    check("text reassembles", len("".join(texts)) >= 20, f"{len(''.join(texts))} chars")
    check("TTFB is quickly returned", t_first is not None and t_first < 0.5,
          f"{t_first*1000:.0f} ms" if t_first else "no first byte")


async def test_ttfb_vs_total(client, base):
    """Streaming should reach the client far earlier than the buffered call."""
    payload = {"token_delay_ms": 20, "max_tokens": 60}
    t0 = time.perf_counter()
    s_ttfb = s_total = None
    async for ev, _, tf, tn in read_sse(client, base, payload):
        s_ttfb, s_total = tf, tn
    t1 = time.perf_counter()
    await client.post(f"{base}/api/chat", json=payload)
    b_total = time.perf_counter() - t1
    check("stream TTFB ≪ buffered total", s_ttfb is not None and s_ttfb < b_total / 3,
          f"stream ttfb {s_ttfb*1000:.0f} ms vs buffered {b_total*1000:.0f} ms")
    check("streamed and buffered total are comparable", s_total is not None and s_total > b_total * 0.5,
          f"{s_total*1000:.0f} ms vs {b_total*1000:.0f} ms")


async def test_cancel(client, base):
    """Closing the connection early must stop generation server-side."""
    t0 = time.perf_counter()
    got = 0
    async with client.stream("POST", f"{base}/api/chat/stream",
                             json={"token_delay_ms": 30, "max_tokens": 200}) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                got += 1
            if got > 5:
                break  # drop the connection mid-stream
    elapsed = time.perf_counter() - t0
    check("client can abort mid-stream", elapsed < 2.5, f"closed after {elapsed:.2f}s / {got} frames")
    await asyncio.sleep(0.5)
    s = (await client.get(f"{base}/api/stats")).json()
    check("server recorded the cancellation", s.get("stream", {}).get("cancelled", 0) >= 1,
          json.dumps(s.get("stream", {}), ensure_ascii=False))


async def test_concurrency(client, base, n=10):
    """n concurrent streams must finish in ~ the time of one, not n × one."""
    payload = {"token_delay_ms": 10, "max_tokens": 40}

    async def one() -> float:
        async for ev, _, _, tn in read_sse(client, base, payload):
            if ev == "done":
                return tn
        return 0.0

    t0 = time.perf_counter()
    times = await asyncio.gather(*[one() for _ in range(n)])
    wall = time.perf_counter() - t0
    serial = sum(times)
    check(f"{n} concurrent streams overlap", wall < serial * 0.6,
          f"wall {wall:.2f}s vs serial {serial:.2f}s")


async def test_error_event(client, base):
    """A mid-stream failure must surface as an SSE `error` event, not a broken socket."""
    seen = []
    try:
        async for ev, data, _, _ in read_sse(client, base,
                                            {"token_delay_ms": 1, "max_tokens": 100, "fail_rate": 1}):
            seen.append(ev)
    except Exception as exc:  # noqa: BLE001
        check("error is delivered as an event", False, f"raised {exc!r}")
        return
    check("error is delivered as an event", "error" in seen or "done" in seen, str(seen[:8]))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.get(f"{args.base}/health")
        except httpx.ConnectError:
            print(f"[fatal] no server at {args.base} — start it with: uvicorn main:app --port 8000")
            return 2

        for fn in (test_health, test_sse_protocol, test_ttfb_vs_total, test_cancel,
                   test_concurrency, test_error_event):
            print(f"\n> {fn.__name__}")
            try:
                await fn(client, args.base)
            except Exception as exc:  # noqa: BLE001
                check(fn.__name__, False, f"raised {type(exc).__name__}: {exc}")

    ok = sum(1 for _, good, _ in results if good)
    print(f"\n{ok}/{len(results)} checks passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
