#!/usr/bin/env python3
"""Run provisioned U2Net on CPU without the rembg download or CLI paths."""
import hashlib
import os
import sys
from pathlib import Path

MODEL_SHA256 = "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"


def remove(source, destination, model):
    model = Path(model).resolve()
    if not model.is_file() or model.stat().st_size != 4574861:
        raise ValueError("Provision the pinned u2netp model before inference")
    if hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("Background model checksum mismatch")
    if Path(destination).exists():
        raise ValueError("Background output must be new")
    os.environ["U2NET_HOME"] = str(model.parent)
    os.environ["OMP_NUM_THREADS"] = "1"
    # Custom session validates this local path; it does not call pooch/download.
    from rembg import new_session
    from rembg import remove as rembg_remove

    session = new_session("u2net_custom", providers=["CPUExecutionProvider"], model_path=str(model))
    result = rembg_remove(Path(source).read_bytes(), session=session, force_return_bytes=True)
    with Path(destination).open("xb") as stream:
        stream.write(result)


if __name__ == "__main__":
    remove(*sys.argv[1:])
