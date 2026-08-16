"""Pi presence handshake writer — run by pi (the coding agent), never whisper.

pi runs this at session start and whenever it responds, so whisper's
state file (see src/pi_state.py) stays fresh:

    python3 scripts/pi_handshake.py --title "PI Code — alignme" --host Code
    python3 scripts/pi_handshake.py --check     # print state + freshness

Exit codes: 0 ok, 2 usage error. Stdlib only — no venv needed.
"""

import argparse
import json
import sys

# Allow running from anywhere; resolve pi_state against the source tree.
sys.path.insert(0, __file__.rsplit("/scripts/", 1)[0])

from src.pi_state import (  # noqa: E402
    PI_STATE_MAX_AGE_S,
    read_pi_state,
    pi_state_fresh,
    write_pi_state,
)


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--title", default="",
        help="Window title fragment identifying pi's window (e.g. 'PI Code — alignme')")
    parser.add_argument(
        "--host", default="Code",
        help="Host app pi runs in (default: Code)")
    parser.add_argument(
        "--session", default="", help="Project/session name (informational)")
    parser.add_argument(
        "--check", action="store_true",
        help="Print the current state and freshness; don't write")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.check:
        state = read_pi_state()
        if state is None:
            print("pi-state: missing")
            return 0
        fresh = pi_state_fresh(state)
        age_hint = ""
        print(
            "pi-state: "
            + ("fresh" if fresh else f"stale (max age {PI_STATE_MAX_AGE_S:.0f}s)")
            + age_hint
        )
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    if not args.title.strip():
        print("error: --title is required (window title fragment)", file=sys.stderr)
        return 2

    state = write_pi_state(
        window_title_fragment=args.title.strip(),
        host_app=args.host.strip() or "Code",
        session=args.session.strip() or None,
    )
    print("pi-state written:")
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
