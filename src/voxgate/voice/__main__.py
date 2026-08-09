"""Run the voice worker.

    uv run --extra voice python -m voxgate.voice --case-id <id>
    uv run --extra voice python -m voxgate.voice --pack-id kyc-uae

A separate process from the API on purpose: it holds Whisper and Kokoro in
memory, and making every API worker carry those would multiply the footprint of
a service that mostly serves JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="VoxGate voice interview worker")
    parser.add_argument("--case-id", help="interview an existing case")
    parser.add_argument("--pack-id", help="open a new case against this pack and interview it")
    parser.add_argument("--api", default=os.environ.get("VOXGATE_API", "http://127.0.0.1:8000"))
    parser.add_argument("--api-key", default=os.environ.get("VOXGATE_API_KEYS", "").split(",")[0] or None)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--whisper-model", default="base")
    parser.add_argument("--voice", default="af_heart")
    args = parser.parse_args()

    if not args.case_id and not args.pack_id:
        parser.error("one of --case-id or --pack-id is required")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from voxgate.voice.pipeline import VoiceConfig, build_transport, run_interview
    from voxgate.voice.session import VoxGateClient, build_interview

    client = VoxGateClient(args.api, args.api_key)
    case_id = args.case_id or client.open_case(args.pack_id)["case_id"]

    config = VoiceConfig(
        host=args.host, port=args.port,
        whisper_model=args.whisper_model, voice_id=args.voice,
    )
    interview = build_interview(client, case_id, greeting=config.greeting)

    print(f"case {case_id}")
    print(f"listening on ws://{args.host}:{args.port}")
    asyncio.run(run_interview(
        transport=build_transport(config), interview=interview, config=config,
    ))


if __name__ == "__main__":
    main()
