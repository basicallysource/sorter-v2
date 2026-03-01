import argparse
import json
from pathlib import Path

DEFAULT_CATEGORY_ID = "misc"
DEFAULT_INPUT_FILE_NAME = "parts_with_categories.json"
DEFAULT_OUTPUT_FILE_NAME = "sorting_profile.json"


def mkParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", dest="input_path", default=None)
    parser.add_argument("--output", dest="output_path", default=None)
    return parser


def getDefaultPaths() -> tuple[Path, Path]:
    client_dir = Path(__file__).resolve().parent.parent
    input_path = client_dir / DEFAULT_INPUT_FILE_NAME
    output_path = client_dir / DEFAULT_OUTPUT_FILE_NAME
    return input_path, output_path


def buildSortingProfile(input_path: Path) -> tuple[dict[str, object], int, int]:
    with input_path.open("r") as f:
        data = json.load(f)

    pieces = data.get("pieces")
    if not isinstance(pieces, list):
        raise ValueError("input json missing pieces list")

    part_to_category: dict[str, str] = {}
    skipped_count = 0

    for part in pieces:
        if not isinstance(part, dict):
            skipped_count += 1
            continue

        part_id = part.get("id")
        category_id = part.get("category_id")

        if part_id is None or category_id is None:
            skipped_count += 1
            continue

        part_to_category[str(part_id)] = str(category_id)

    sorting_profile = {
        "version": 1,
        "default_category_id": DEFAULT_CATEGORY_ID,
        "part_to_category": part_to_category,
    }
    return sorting_profile, len(part_to_category), skipped_count


def main() -> int:
    parser = mkParser()
    args = parser.parse_args()

    default_input_path, default_output_path = getDefaultPaths()
    input_path = Path(args.input_path) if args.input_path else default_input_path
    output_path = Path(args.output_path) if args.output_path else default_output_path

    sorting_profile, mapped_count, skipped_count = buildSortingProfile(input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(sorting_profile, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"wrote {output_path}")
    print(f"mapped_parts={mapped_count}")
    print(f"skipped_parts={skipped_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
