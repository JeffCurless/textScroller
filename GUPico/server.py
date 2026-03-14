# server.py — Async HTTP server for the Galactic Unicorn text scroller.
#
# run_server() is the second long-running coroutine started by main.py.
# It listens on HTTP_PORT for incoming TCP connections and dispatches them
# to _handle_client(), which parses the request and acts on it.
#
# API endpoints:
#   POST /message  — queue a message {"text": "...", "color": [R,G,B]}
#   POST /settings — adjust brightness, speed, or pause state
#   GET  /status   — return current display state as JSON
#   POST /clear    — clear the queue and reset to the default message
#
# MicroPython's uasyncio is single-threaded and cooperative, so only one
# client is handled at a time.  The display loop continues to run between
# awaits inside the request handler.

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import json
from config import HTTP_PORT, HTTP_HOST, MAX_QUEUE_DEPTH, DEFAULT_COLOR


def _response(status, body_dict, writer):
    """Serialise body_dict as JSON and write a complete HTTP response.

    Does not flush or close the connection — the caller must await _close().

    Args:
        status:    HTTP status line string, e.g. "200 OK" or "400 Bad Request".
        body_dict: Python dict that will be JSON-encoded as the response body.
        writer:    asyncio StreamWriter for the current connection.
    """
    body   = json.dumps(body_dict)
    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(status, len(body))
    writer.write((header + body).encode())


async def _close(writer):
    """Flush any buffered output and fully release the TCP connection.

    drain() flushes any bytes still in the send buffer.
    close() initiates the TCP close handshake.
    wait_closed() blocks until the underlying lwIP PCB (Protocol Control
    Block) is fully released back to the pool.

    All three calls are wrapped in try/except because the client may have
    already closed its end, which can raise exceptions we can safely ignore.

    Without wait_closed(), sockets linger in TIME_WAIT and consume a PCB
    slot.  The Pico W's lwIP stack has a fixed pool of ~5 PCBs; exhausting
    the pool causes all subsequent TCP connections to be refused even though
    the device is still reachable by ping (ICMP is unaffected).
    """
    try:
        await writer.drain()
    except Exception:
        pass
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


async def _read_request(reader):
    """Read a complete HTTP request from the stream.

    MicroPython's reader.read(n) returns as soon as *any* data is available,
    which is often just the HTTP headers.  The request body (JSON payload)
    typically arrives in a second TCP segment.  This function:
      1. Reads chunks until the header/body separator (\\r\\n\\r\\n) is seen.
      2. Parses Content-Length from the headers.
      3. Reads additional chunks until the full body has been received.

    Returns:
        bytes: The complete raw HTTP request, or None on timeout/error.
    """
    raw = b""

    # Phase 1: collect bytes until the blank line separating headers from body
    try:
        while b"\r\n\r\n" not in raw:
            chunk = await asyncio.wait_for(reader.read(1024), timeout=3.0)
            if not chunk:
                break   # connection closed by client
            raw += chunk
    except Exception:
        return None  # timeout or connection error — caller will close

    # Phase 2: read any remaining body bytes indicated by Content-Length
    try:
        header_block = raw.split(b"\r\n\r\n", 1)[0].decode()

        # Scan header lines (skip the request line at index 0)
        content_length = 0
        for line in header_block.split("\r\n")[1:]:
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break

        body_so_far = raw.split(b"\r\n\r\n", 1)[1]
        while len(body_so_far) < content_length:
            # Request exactly the number of bytes still outstanding
            chunk = await asyncio.wait_for(
                reader.read(content_length - len(body_so_far)), timeout=3.0)
            if not chunk:
                break
            body_so_far += chunk

        # Reassemble as a single bytes object for the caller
        return (header_block + "\r\n\r\n" + body_so_far.decode()).encode()
    except Exception:
        # If Content-Length parsing fails, return whatever we have; the
        # handler will attempt to parse it and return 400 if the body is absent.
        return raw


async def _handle_client(reader, writer, state):
    """Parse one HTTP request and dispatch to the appropriate handler.

    Args:
        reader: asyncio StreamReader for the incoming connection.
        writer: asyncio StreamWriter for the outgoing response.
        state:  Shared AppState instance.
    """
    # Read the full request (headers + body)
    raw = await _read_request(reader)
    if not raw:
        await _close(writer)
        return

    try:
        request = raw.decode()
    except Exception:
        await _close(writer)
        return

    # Parse the request line ("GET /status HTTP/1.1")
    lines        = request.split("\r\n")
    request_line = lines[0].split() if lines else []
    if len(request_line) < 2:
        await _close(writer)
        return

    method = request_line[0]   # e.g. "POST"
    path   = request_line[1]   # e.g. "/message"

    # Extract the request body (everything after the blank line)
    body = ""
    if "\r\n\r\n" in request:
        body = request.split("\r\n\r\n", 1)[1]

    # Attempt to decode the body as JSON; leave data as {} on failure
    data = {}
    if body:
        try:
            data = json.loads(body)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Route dispatch
    # ------------------------------------------------------------------

    if method == "POST" and path == "/message":
        # Queue a new message for the display.
        # Required field: "text" (string)
        # Optional field: "color" ([R, G, B] integers 0–255)
        if "text" not in data:
            _response("400 Bad Request", {"error": "missing 'text' field"}, writer)
        elif len(state.message_queue) >= MAX_QUEUE_DEPTH:
            # Refuse new messages when the queue is full to prevent unbounded growth
            _response("429 Too Many Requests", {"error": "queue full"}, writer)
        else:
            color = data.get("color", list(DEFAULT_COLOR))
            if isinstance(color, list) and len(color) == 3:
                color = tuple(color)   # store as tuple to match DEFAULT_COLOR type
            else:
                color = DEFAULT_COLOR  # fall back to white for invalid color values
            state.message_queue.append({"text": str(data["text"]), "color": color})
            _response("200 OK", {"status": "ok", "queued": len(state.message_queue)}, writer)

    elif method == "POST" and path == "/settings":
        # Adjust runtime settings.  All fields are optional; send only what you
        # want to change.
        # "brightness" — float 0.0–1.0
        # "speed"      — int ms per pixel (minimum 10)
        # "pause"      — bool
        if "brightness" in data:
            state.brightness = max(0.0, min(1.0, float(data["brightness"])))
        if "speed" in data:
            state.scroll_speed_ms = max(10, int(data["speed"]))
        if "pause" in data:
            state.paused = bool(data["pause"])
        _response("200 OK", {"status": "ok"}, writer)

    elif method == "GET" and path == "/status":
        # Return a snapshot of the current display state
        _response("200 OK", {
            "current":    state.current_message["text"],
            "queued":     len(state.message_queue),
            "paused":     state.paused,
            "brightness": state.brightness,
            "ip":         state.ip_address,
        }, writer)

    elif method == "POST" and path == "/clear":
        # Discard all queued messages and reset the display to the default message
        state.message_queue.clear()
        state.current_message = {"text": "Galactic Unicorn", "color": DEFAULT_COLOR}
        state.scroll_x = 53   # restart scroll from the right edge
        _response("200 OK", {"status": "ok"}, writer)

    else:
        _response("404 Not Found", {"error": "not found"}, writer)

    await _close(writer)


async def run_server(state):
    """Start the HTTP server and keep it running indefinitely.

    asyncio.start_server() registers handler() as the callback for each new
    TCP connection and returns immediately.  The while loop below keeps this
    coroutine alive so the server continues accepting connections alongside
    the display coroutine.

    Args:
        state: Shared AppState instance passed through to each request handler.
    """
    async def handler(reader, writer):
        await _handle_client(reader, writer, state)

    await asyncio.start_server(handler, HTTP_HOST, HTTP_PORT)

    # Keep this coroutine suspended so the event loop stays alive.
    # Sleeping for a long interval is more efficient than a tight loop.
    while True:
        await asyncio.sleep(3600)
