"""SecureFile Application Protocol (SFAP/1) - frame codec.

Frame layout (24-byte fixed header, big endian):

    0               1               2               3
    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
   +---------------+---------------+---------------+---------------+
   |   magic 'S''F' | version |  type | flags | rsvd  |           |
   +---------------+---------------+---------------+---------------+
   |                      stream_id (uint32)                       |
   +---------------------------------------------------------------+
   |                       sequence (uint32)                        |
   +---------------------------------------------------------------+
   |                     body length (uint32)                       |
   +---------------------------------------------------------------+
   |                    payload length (uint32)                     |
   +-------------------------------+---------------+---------------+
   |   header CRC16 (uint16)      |  body: UTF-8 JSON  | payload   |
   +-------------------------------+---------------+---------------+

The header carries only transport-level semantics (framing, multiplexing,
ordering, integrity); every business field lives in the JSON body, which keeps
the wire format extensible without touching the binary layout.
"""

from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Any

MAGIC = b"SF"
VERSION = 1

# magic(2s) ver(B) type(B) flags(B) reserved(B) stream(I) seq(I) body_len(I) payload_len(I)
HEADER_PREFIX = struct.Struct(">2sBBBBIIII")
HEADER_CRC = struct.Struct(">H")
HEADER_STRUCT = struct.Struct(">2sBBBBIIIIH")
HEADER_LEN = HEADER_STRUCT.size  # 24
PREFIX_LEN = HEADER_PREFIX.size  # 22
assert HEADER_LEN == 24

MAX_BODY = 16 * 1024
MAX_PAYLOAD = 1024 * 1024
MIN_PAYLOAD = 256 + 24  # keeps a DATA frame well under one ethernet MTU burst


class Msg(IntEnum):
    """Message type registry. The high nibble encodes the module."""

    LOGIN_REQ = 0x01
    LOGIN_RESP = 0x02
    LOGOUT_REQ = 0x03
    LOGOUT_RESP = 0x04

    LIST_REQ = 0x10
    LIST_RESP = 0x11
    STAT_REQ = 0x12
    STAT_RESP = 0x13

    UPLOAD_REQ = 0x20
    UPLOAD_RESP = 0x21
    DATA = 0x22
    DATA_ACK = 0x23
    UPLOAD_END = 0x24
    UPLOAD_RESP_END = 0x25
    CANCEL = 0x26
    DOWNLOAD_REQ = 0x27
    DOWNLOAD_RESP = 0x28

    MKDIR_REQ = 0x30
    MKDIR_RESP = 0x31
    DELETE_REQ = 0x32
    DELETE_RESP = 0x33
    RENAME_REQ = 0x34
    RENAME_RESP = 0x35

    PING = 0x40
    PONG = 0x41

    ERROR = 0x60
    BYE = 0x70
    BYE_ACK = 0x71


class Flags(IntFlag):
    LAST = 0x01      # last frame of a multi-frame transfer
    RESUME = 0x02    # resume negotiation present
    ACKREQ = 0x04    # sender wants an immediate acknowledgement
    ERROR = 0x08     # business-level failure flag


class ErrorCode:
    OK = "OK"
    BAD_FRAME = "BAD_FRAME"
    NOT_AUTH = "NOT_AUTH"
    AUTH_FAILED = "AUTH_FAILED"
    LOCKED = "LOCKED"
    DENIED = "DENIED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    TOO_LARGE = "TOO_LARGE"
    RATE_LIMITED = "RATE_LIMITED"
    INTEGRITY = "INTEGRITY"
    INTERNAL = "INTERNAL"
    SHUTDOWN = "SHUTDOWN"


class ProtocolError(Exception):
    """Raised when a peer violates the framing contract."""


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE, used to reject corrupted headers early."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass(slots=True)
class Frame:
    type: int
    body: dict[str, Any] = field(default_factory=dict)
    payload: bytes = b""
    stream: int = 0
    seq: int = 0
    flags: int = 0

    def encode(self) -> bytes:
        body = b"" if not self.body else json.dumps(
            self.body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(body) > MAX_BODY:
            raise ProtocolError(f"body too large: {len(body)}")
        if len(self.payload) > MAX_PAYLOAD:
            raise ProtocolError(f"payload too large: {len(self.payload)}")
        head = HEADER_PREFIX.pack(
            MAGIC, VERSION, int(self.type) & 0xFF, int(self.flags) & 0xFF, 0,
            self.stream & 0xFFFFFFFF, self.seq & 0xFFFFFFFF,
            len(body), len(self.payload),
        )
        return head + HEADER_CRC.pack(crc16_ccitt(head)) + body + self.payload

    @property
    def is_last(self) -> bool:
        return bool(self.flags & Flags.LAST)


def parse_header(raw: bytes) -> dict[str, Any]:
    if len(raw) != HEADER_LEN:
        raise ProtocolError("short header")
    magic, ver, mtype, flags, rsvd, stream, seq, blen, plen = HEADER_PREFIX.unpack(raw[:PREFIX_LEN])
    (crc,) = HEADER_CRC.unpack(raw[PREFIX_LEN:HEADER_LEN])
    if magic != MAGIC:
        raise ProtocolError("bad magic")
    if ver != VERSION:
        raise ProtocolError(f"unsupported version {ver}")
    if crc != crc16_ccitt(raw[:PREFIX_LEN]):
        raise ProtocolError("header crc mismatch")
    if blen > MAX_BODY or plen > MAX_PAYLOAD:
        raise ProtocolError("frame exceeds negotiated limits")
    return {"type": mtype, "flags": flags, "stream": stream, "seq": seq,
            "body_len": blen, "payload_len": plen}


async def read_frame(reader: asyncio.StreamReader) -> Frame | None:
    """Read one frame. Returns None on a clean EOF at a frame boundary."""
    try:
        raw = await reader.readexactly(HEADER_LEN)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise ProtocolError("truncated header") from exc
    meta = parse_header(raw)
    body_raw = await reader.readexactly(meta["body_len"]) if meta["body_len"] else b""
    payload = await reader.readexactly(meta["payload_len"]) if meta["payload_len"] else b""
    try:
        body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise ProtocolError("body must be a JSON object")
    return Frame(type=meta["type"], flags=meta["flags"], stream=meta["stream"],
                 seq=meta["seq"], body=body, payload=payload)


def build(mtype: Msg | int, *, stream: int = 0, seq: int = 0, flags: int = 0,
          body: dict[str, Any] | None = None, payload: bytes = b"") -> Frame:
    return Frame(type=int(mtype), stream=stream, seq=seq, flags=flags,
                 body=body or {}, payload=payload)


def error_frame(code: str, message: str, *, stream: int = 0, **extra: Any) -> Frame:
    body = {"code": code, "message": message, **extra}
    return build(Msg.ERROR, stream=stream, flags=Flags.ERROR, body=body)


class FrameWriter:
    """Serialises frames onto one stream so concurrent tasks never interleave."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        self._lock = asyncio.Lock()
        self.bytes_out = 0
        self.frames_out = 0

    async def send(self, frame: Frame) -> None:
        blob = frame.encode()
        async with self._lock:
            self._writer.write(blob)
            await self._writer.drain()
            self.bytes_out += len(blob)
            self.frames_out += 1

    async def close(self) -> None:
        async with self._lock:
            if not self._writer.is_closing():
                self._writer.close()
            # TLS transports on Windows can take seconds to report connection_lost;
            # the FIN is already queued by close(), so do not block the session.
            await asyncio.sleep(0)


def peer_common_name(ssl_object) -> str | None:
    """Extract CN from the verified peer certificate (mutual TLS)."""
    if ssl_object is None:
        return None
    cert = ssl_object.getpeercert()
    if not cert:
        return None
    for rdn in cert.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                return value
    return None


def fingerprint_of(cert_der: bytes) -> str:
    import hashlib
    return hashlib.sha256(cert_der).hexdigest()
