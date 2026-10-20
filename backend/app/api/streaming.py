"""Small helpers for translating graph events into safe answer-only SSE tokens."""
from __future__ import annotations

import json
import re
from typing import Any


def sse_event(name: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {data}\n\n"


def chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def extract_answer_json_fragment(buffer: str) -> str | None:
    """Return the available raw JSON string contents for the `answer` property."""
    match = re.search(r'"answer"\s*:\s*"', buffer)
    if not match:
        return None
    start = match.end()
    escaped = False
    for index in range(start, len(buffer)):
        char = buffer[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return buffer[start:index]
    return buffer[start:]


def decode_json_string_fragment(raw: str) -> str:
    """Decode complete JSON escapes while holding an incomplete escape for the next chunk."""
    simple = {
        '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
        "n": "\n", "r": "\r", "t": "\t",
    }
    output: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char != "\\":
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(raw):
            break
        escaped = raw[index + 1]
        if escaped in simple:
            output.append(simple[escaped])
            index += 2
            continue
        if escaped == "u":
            if index + 6 > len(raw):
                break
            codepoint = int(raw[index + 2:index + 6], 16)
            if 0xD800 <= codepoint <= 0xDBFF:
                next_start = index + 6
                if raw[next_start:next_start + 2] != "\\u" or next_start + 6 > len(raw):
                    break
                low = int(raw[next_start + 2:next_start + 6], 16)
                if not 0xDC00 <= low <= 0xDFFF:
                    output.append("�")
                    index += 6
                    continue
                codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)
                index += 12
            else:
                index += 6
            output.append(chr(codepoint))
            continue
        # Invalid model escape: preserve it visibly and continue without crashing the stream.
        output.append(escaped)
        index += 2
    return "".join(output)
