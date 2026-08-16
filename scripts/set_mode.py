#!/usr/bin/env python
"""Set whisper's output mode in config.toml — the voice-config bridge.

Pi (via the whisper-vtt skill) runs this when a dictation asks to
switch modes, e.g. "change auto_send to protected".

Usage:
    python scripts/set_mode.py <mode> [--config PATH]

    mode: clipboard | auto_paste | auto_send | protected

Validates against config_manager's VALID_OUTPUT_MODES and rewrites the
`mode` line in the [output] section atomically (temp file + replace),
preserving all other lines and comments.

Exit codes: 0 success, 1 invalid mode, 2 config file problem.
"""

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config.toml"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config_manager import VALID_OUTPUT_MODES  # noqa: E402


def set_mode(config_path: Path, mode: str) -> int:
    if mode not in VALID_OUTPUT_MODES:
        print(
            f"Invalid mode {mode!r}. Valid: "
            + ", ".join(sorted(VALID_OUTPUT_MODES)),
            file=sys.stderr,
        )
        return 1

    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        print(f"Could not read {config_path}: {e}", file=sys.stderr)
        return 2

    in_output = False
    replaced = False
    for i, line in enumerate(lines):
        if re.match(r"^\s*\[output\]", line):
            in_output = True
            continue
        if in_output and re.match(r"^\s*\[", line):
            break
        if in_output and re.match(r"^\s*mode\s*=", line):
            indent = re.match(r"^(\s*)", line).group(1)
            lines[i] = f'{indent}mode = "{mode}"'
            replaced = True
            break

    if not replaced:
        print(
            f"No [output] section with a `mode` line found in {config_path}",
            file=sys.stderr,
        )
        return 2

    try:
        fd, tmp = tempfile.mkstemp(
            dir=str(config_path.parent), prefix=".config.toml.", text=True
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, config_path)
    except OSError as e:
        print(f"Could not write {config_path}: {e}", file=sys.stderr)
        return 2

    print(f"mode set to {mode!r} in {config_path} (restart whisper to load)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    return set_mode(args.config, args.mode)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
