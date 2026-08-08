"""Conformance: our hand-rolled wire format (<-> pipecat's ProtobufFrameSerializer.

The browser client encodes/decodes pipecat's protobuf wire format by hand (no
protobuf library in the browser). This test proves that encoding is byte-for-byte
compatible with pipecat's own serializer, so whatever the dashboard.js client
sends/receives round-trips correctly with the real server pipeline.
"""
import pytest

from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, TextFrame
from pipecat.serializers.protobuf import ProtobufFrameSerializer

from voxgate.service.voice import protobuf as pb


def _sample_pcm(size: int = 640) -> bytes:
    return bytes((i * 31) & 0xFF for i in range(size))


def test_encode_audio_frame_deserializes_to_input_audio():
    pcm = _sample_pcm()
    payload = pb.encode_audio_frame(pcm, 16000, 1)
    frame = pytest.importorskip("pipecat").serializers.protobuf
    serializer = ProtobufFrameSerializer()

    import asyncio
    parsed = asyncio.run(serializer.deserialize(payload))

    assert isinstance(parsed, InputAudioRawFrame)
    assert bytes(parsed.audio) == pcm
    assert parsed.sample_rate == 16000
    assert parsed.num_channels == 1


def test_encode_text_frame_deserializes_to_text():
    serializer = ProtobufFrameSerializer()
    payload = pb.encode_text_frame("Yes, my name is Fatima.")

    import asyncio
    parsed = asyncio.run(serializer.deserialize(payload))

    assert isinstance(parsed, TextFrame)
    assert parsed.text == "Yes, my name is Fatima."


def test_output_audio_decodes_to_browser_payload():
    pcm = _sample_pcm(1024)
    out = OutputAudioRawFrame(audio=pcm, sample_rate=24000, num_channels=1)
    serializer = ProtobufFrameSerializer()

    import asyncio
    payload = asyncio.run(serializer.serialize(out))
    assert isinstance(payload, bytes)

    decoded = pb.decode_frame(payload)
    assert decoded["audio"]["data"] == pcm
    assert decoded["audio"]["sample_rate"] == 24000
    assert decoded["audio"]["num_channels"] == 1


def test_output_text_decodes_to_text():
    serializer = ProtobufFrameSerializer()

    import asyncio
    payload = asyncio.run(serializer.serialize(TextFrame(text="Thank you.")))
    assert isinstance(payload, bytes)

    decoded = pb.decode_frame(payload)
    assert decoded["text"] == "Thank you."


def test_decode_frame_ignores_unsupported_oneof_gracefully():
    # A Frame with no branch set (all-zero message) must not blow up.
    assert pb.decode_frame(b"\x00"[:0]) == {}


def test_varint_roundtrip_wide_values():
    for value in [0, 1, 127, 128, 300, 65535, 16000, 2**32 - 1]:
        decoded, _ = pb._read_varint(pb._varint(value), 0)
        assert decoded == value
