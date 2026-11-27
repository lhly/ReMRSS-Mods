#!/usr/bin/env python3
"""Publish the exact reviewed index in one signed file, without exposing the signing key."""
import argparse
import base64
from pathlib import Path
import tempfile
import time

from catalog import index_for, load, require, serialize
from remrss_mod import openssl

FORMAT = "remrss.community.index.v1"
MAX_INDEX_BYTES = 256 * 1024
MAX_SIGNED_BYTES = 352 * 1024
SIGNED_NAME = "index.signed.json"


def signing_bytes(sequence, payload):
    return f"{FORMAT}\0{sequence}\0".encode("ascii") + payload


def verify_envelope(path, public_key):
    envelope = load(path, MAX_SIGNED_BYTES)
    require(isinstance(envelope, dict) and envelope.keys() == {"format", "sequence", "payload", "signature"} and
            envelope["format"] == FORMAT, "invalid signed directory format")
    sequence = envelope["sequence"]
    require(type(sequence) is int and 0 < sequence < 2**63, "invalid directory sequence")
    payload = base64.b64decode(envelope["payload"], validate=True)
    signature = base64.b64decode(envelope["signature"], validate=True)
    require(0 < len(payload) <= MAX_INDEX_BYTES and 256 <= len(signature) <= 512, "invalid signed directory size")
    with tempfile.TemporaryDirectory(prefix="remrss-catalog-") as folder:
        detached = Path(folder) / "signature"
        detached.write_bytes(signature)
        openssl("dgst", "-sha256", "-verify", public_key, "-signature", detached,
                input_bytes=signing_bytes(sequence, payload))
    return payload, sequence


def canonical_index(root):
    payload = serialize(index_for(root))
    require((root / "index.json").read_bytes() == payload, "reviewed index.json does not match entries")
    return payload


def sign(root, private_key, public_key):
    path = root / SIGNED_NAME
    payload = canonical_index(root)
    previous = verify_envelope(path, public_key)[1] if path.exists() else 0
    sequence = max(int(time.time()), previous + 1)
    signature = openssl("dgst", "-sha256", "-sign", private_key, input_bytes=signing_bytes(sequence, payload))
    envelope = {
        "format": FORMAT,
        "sequence": sequence,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    # Publish both bytes and signature atomically so a CDN cannot mix revisions.
    with tempfile.TemporaryDirectory(prefix=".catalog-sign-", dir=root) as folder:
        staged = Path(folder) / SIGNED_NAME
        staged.write_bytes(serialize(envelope))
        verify_envelope(staged, public_key)
        staged.replace(path)
    return sequence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("sign", "verify"):
        command = commands.add_parser(name)
        command.add_argument("root", type=Path)
        command.add_argument("--public-key", type=Path, required=True)
        if name == "sign":
            command.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "sign":
            sequence = sign(args.root, args.key, args.public_key)
        else:
            payload, sequence = verify_envelope(args.root / SIGNED_NAME, args.public_key)
            require(payload == canonical_index(args.root), "signed payload differs from reviewed index.json")
        print(f"Verified community directory sequence {sequence}")
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
