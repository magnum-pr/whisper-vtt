"""Download a whisper.cpp GGML model for offline use.

Downloads from the official whisper.cpp Hugging Face repo (the same files
pywhispercpp consumes). Models:

    tiny.en   ~77MB   (fastest)
    base.en   ~141MB  (default — good speed/accuracy balance)
    small.en  ~466MB  (most accurate of the small set)

Usage:
    python scripts/download_model.py base.en
    python scripts/download_model.py tiny.en --output models/custom-name.bin
"""

import argparse
import sys
import urllib.request
from pathlib import Path

HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

VALID_MODELS = {
    "tiny.en": "ggml-tiny.en.bin",
    "base.en": "ggml-base.en.bin",
    "small.en": "ggml-small.en.bin",
}


def main():
    parser = argparse.ArgumentParser(
        description="Download a whisper.cpp GGML model for offline use."
    )
    parser.add_argument(
        "model",
        nargs="?",
        default="base.en",
        help=f"Model name ({', '.join(VALID_MODELS)}). Default: base.en",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: models/<model>.bin)",
    )
    args = parser.parse_args()

    model_name = args.model
    if model_name not in VALID_MODELS:
        print(
            f"Unknown model '{model_name}'. Valid options: "
            f"{', '.join(VALID_MODELS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    file_name = VALID_MODELS[model_name]
    output_path = Path(args.output) if args.output else Path(f"models/{file_name}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        print(f"Model already exists: {output_path} ({output_path.stat().st_size // (1024*1024)} MB)")
        return

    url = f"{HF_BASE}/{file_name}"
    print(f"Downloading {model_name} → {output_path} ...")
    print(f"  {url}")
    try:
        urllib.request.urlretrieve(url, output_path)
    except Exception as e:
        print(f"ERROR downloading model: {e}", file=sys.stderr)
        output_path.unlink(missing_ok=True)
        sys.exit(1)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Done: {output_path} ({size_mb:.0f} MB)")
    print(f"Tip: set [model] path = \"{output_path.as_posix()}\" in config.toml")


if __name__ == "__main__":
    main()
