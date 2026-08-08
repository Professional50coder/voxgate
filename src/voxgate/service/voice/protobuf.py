"""Minimal, dependency-free encoder/decoder for pipecat's WebSocket wire format.

This mirrors the exact protobuf schema pipecat ships in
``pipecat.frames.protobufs.frames_pb2`` and speaks on its
``ProtobufFrameSerializer``, so the browser client and the server converge on a
single binary representation:

- ``Frame`` message, oneof ``frame``: ``text=1``, ``audio=2``,
  ``transcription=3``, ``message=4``, ``interruption=5``.
- ``AudioRawFrame``: ``id=1`` (uint64), ``name=2`` (string), ``audio=3`` (bytes,
  int16 little-endian PCM), ``sample_rate=4`` (uint32), ``num_channels=5``
  (uint32), ``pts=6`` (uint64).
- ``TextFrame``: ``id=1`` (uint64), ``name=2`` (string), ``text=3`` (string).

Only the protobuf ``varint`` (0) and ``length-delimited`` (2) wire types are
needed for the fields we exchange. Everything here is mirrored verbatim by the
client in ``dashboard.js``; this module exists so tests can prove the wire
format against pipecat's own serializer without a real browser.
"""
from __future__ import annotations

from typing import Any

WIRE_VARINT = 0
WIRE_LEN = 2


def _varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1  # uint64-ish two's complement for negative ids
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _len_field(field: int, payload: bytes) -> bytes:
    return _tag(field, WIRE_LEN) + _varint(len(payload)) + payload


def _u32_field(field: int, value: int) -> bytes:
    return _tag(field, WIRE_VARINT) + _varint(value)


def encode_audio_frame(data: bytes, sample_rate: int, num_channels: int = 1) -> bytes:
    """Encode a ``Frame.audio`` payload (int16 LE PCM) for sending to the server.

    The result is exactly what pipecat's ``ProtobufFrameSerializer.deserialize``
    accepts as an ``InputAudioRawFrame``.
    """
    inner = b"".join([
        _len_field(3, data),
        _u32_field(4, sample_rate),
        _u32_field(5, num_channels),
    ])
    return _len_field(2, inner)


def encode_text_frame(text: str) -> bytes:
    """Encode a ``Frame.text`` payload (typed user input) for sending to the server."""
    inner = _len_field(3, text.encode("utf-8"))
    return _len_field(1, inner)


def _parse_message(data: bytes) -> dict[int, tuple[int, Any]]:
    """Parse a protobuf message into {field_number: (wire_type, value)}.

    ``value`` is an ``int`` for varint fields and ``bytes`` for length-delimited
    fields.
    """
    fields: dict[int, tuple[int, Any]] = {}
    i = 0
    n = len(data)
    while i < n:
        tag, i = _read_varint(data, i)
        field = tag >> 3
        wire = tag & 7
        if wire == WIRE_VARINT:
            value, i = _read_varint(data, i)
            fields[field] = (wire, value)
        elif wire == WIRE_LEN:
            length, i = _read_varint(data, i)
            value = data[i:i + length]
            i += length
            fields[field] = (wire, value)
        else:
            raise ValueError(f"unsupported wire type {wire}")
    return fields


def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if i >= len(data):
            raise ValueError("truncated varint")
        byte = data[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def decode_frame(data: bytes) -> dict[str, Any]:
    """Decode a ``Frame`` protobuf into a plain dict description.

    Returns keys: ``text`` (str), ``audio`` ({data/sample_rate/num_channels}),
    ``message`` (str JSON), present only when that oneof branch was set.
    """
    out: dict[str, Any] = {}
    for field, (wire, value) in _parse_message(data).items():
        if wire != WIRE_LEN:
            continue
        if field == 1:  # text -> TextFrame.text = 3
            inner = _parse_message(value)
            out["text"] = _field_string(inner, 3)
        elif field == 2:  # audio -> AudioRawFrame
            inner = _parse_message(value)
            out["audio"] = {
                "data": _field_bytes(inner, 3),
                "sample_rate": _field_int(inner, 4),
                "num_channels": _field_int(inner, 5),
            }
        elif field == 3:  # transcription
            inner = _parse_message(value)
            out["transcription"] = _field_string(inner, 3)
        elif field == 4:  # message -> MessageFrame.data = 1
            inner = _parse_message(value)
            out["message"] = _field_string(inner, 1)
        elif field == 5:  # interruption
            out["interruption"] = True
    return out


def _field_int(fields: dict[int, tuple[int, Any]], num: int) -> int | None:
    entry = fields.get(num)
    return entry[1] if entry is not None else None


def _field_string(fields: dict[int, tuple[int, Any]], num: int) -> str:
    entry = fields.get(num)
    value = entry[1] if entry is not None else b""
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _field_bytes(fields: dict[int, tuple[int, Any]], num: int) -> bytes:
    entry = fields.get(num)
    value = entry[1] if entry is not None else b""
    return value if isinstance(value, bytes) else b""