import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'client'))

from pydantic2ts import generate_typescript_defs
from defs.events import SocketEvent
from typing import get_args


def exportSocketEvent(output_path: str) -> None:
    generate_typescript_defs(
        "defs.events",
        output_path,
        exclude=["ServerToMainThreadEvent", "MainThreadToServerCommand"]
    )

    # dynamically generate SocketEvent union from Python union type
    event_types = get_args(SocketEvent)
    if not event_types:
        # single type union gets simplified by Python
        union_str = SocketEvent.__name__
    else:
        union_str = " | ".join([t.__name__ for t in event_types])

    with open(output_path, 'a') as f:
        f.write(f"\nexport type SocketEvent = {union_str};\n")


def main() -> None:
    output_path = sys.argv[1] if len(sys.argv) > 1 else "events.ts"
    exportSocketEvent(output_path)


if __name__ == "__main__":
    main()
