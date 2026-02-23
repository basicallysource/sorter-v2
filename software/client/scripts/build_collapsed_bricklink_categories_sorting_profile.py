import argparse
import json
from collections import Counter
from pathlib import Path

DEFAULT_CATEGORY_ID = "misc"
DEFAULT_INPUT_FILE_NAME = "parts_with_categories.json"
DEFAULT_CATEGORIES_FILE_NAME = "bricklink_categories.json"
DEFAULT_OUTPUT_FILE_NAME = "collapsed_bricklink_categories_sorting_profile.json"

COMBINED_CATEGORY_GROUPS = [
    [26, 28],
    [4, 27],
    [37, 38, 117],
    [5, 7, 8, 1253],
    [31, 32, 379],
    [438],
    [42, 583],
    [22, 40, 45, 46, 88, 112, 105],
    [12, 540, 642, 13, 81, 113, 115, 479, 79, 90, 103],
    [91],
    [6, 10, 11, 21, 107, 116],
    [25, 95, 99, 175],
    [86, 145, 146, 147, 148, 184, 106],
    [16, 18, 19, 20, 142, 150, 238, 418, 606, 636, 847, 1116, 911, 912, 913, 915, 1252, 569, 771],
    [162, 231, 246, 1078, 161, 234],
    [43, 111, 532, 1027, 77, 225],
    [3, 72, 73, 74, 93, 114, 131, 424, 30, 999],
    [124, 128, 122, 237, 441, 450],
    [119, 121, 123, 411, 463, 735, 504],
    [36, 133, 134, 135, 136, 137, 138, 139, 140, 141, 154, 159, 242, 483, 522, 527, 528, 530, 542, 638, 229, 991, 87, 152],
    [2, 130, 243],
    [1, 14, 76, 98],
    [48, 85, 102, 153, 394, 412, 413],
    [273, 235, 749, 992, 994],
    [167, 417, 420, 487, 488, 524, 585, 639, 640, 641, 707, 845, 846, 1037, 1038, 1121, 537, 439, 294, 437],
    [490, 575, 1059, 473, 978, 989, 990, 1215],
    [423, 444],
]


def mkParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", dest="input_path", default=None)
    parser.add_argument("--categories", dest="categories_path", default=None)
    parser.add_argument("--output", dest="output_path", default=None)
    return parser


def getDefaultPaths() -> tuple[Path, Path, Path]:
    client_dir = Path(__file__).resolve().parent.parent
    input_path = client_dir / DEFAULT_INPUT_FILE_NAME
    categories_path = client_dir / DEFAULT_CATEGORIES_FILE_NAME
    output_path = client_dir / DEFAULT_OUTPUT_FILE_NAME
    return input_path, categories_path, output_path


def mkCombinedCategoryMap() -> dict[int, str]:
    category_to_combined: dict[int, str] = {}
    for group in COMBINED_CATEGORY_GROUPS:
        combined_category_id = "-".join(str(category_id) for category_id in sorted(group))
        for category_id in group:
            if category_id in category_to_combined:
                raise ValueError(f"duplicate category in groups: {category_id}")
            category_to_combined[category_id] = combined_category_id
    return category_to_combined


def loadBricklinkCategoryNames(categories_path: Path) -> dict[int, str]:
    with categories_path.open("r") as f:
        data = json.load(f)
    categories = data.get("categories")
    if not isinstance(categories, list):
        raise ValueError("bricklink categories json missing categories list")
    category_names: dict[int, str] = {}
    for category in categories:
        if not isinstance(category, dict):
            continue
        category_id = category.get("id")
        category_name = category.get("name")
        if category_id is None or category_name is None:
            continue
        category_names[int(category_id)] = str(category_name)
    return category_names


def buildSortingProfile(
    input_path: Path,
    category_to_combined: dict[int, str],
) -> tuple[dict[str, object], int, int, Counter[str]]:
    with input_path.open("r") as f:
        data = json.load(f)

    pieces = data.get("pieces")
    if not isinstance(pieces, list):
        raise ValueError("input json missing pieces list")

    part_to_category: dict[str, str] = {}
    skipped_count = 0
    combined_counts: Counter[str] = Counter()
    used_categories: set[int] = set()

    for part in pieces:
        if not isinstance(part, dict):
            skipped_count += 1
            continue

        part_id = part.get("id")
        category_id = part.get("category_id")

        if part_id is None or category_id is None:
            skipped_count += 1
            continue

        category_id_int = int(category_id)
        used_categories.add(category_id_int)
        combined_category_id = category_to_combined.get(category_id_int)
        if combined_category_id is None:
            raise ValueError(f"unmapped category_id in parts file: {category_id_int}")

        part_to_category[str(part_id)] = combined_category_id
        combined_counts[combined_category_id] += 1

    if len(combined_counts) != len(COMBINED_CATEGORY_GROUPS):
        raise ValueError(
            f"expected {len(COMBINED_CATEGORY_GROUPS)} combined categories, got {len(combined_counts)}"
        )

    sorting_profile = {
        "version": 1,
        "default_category_id": DEFAULT_CATEGORY_ID,
        "part_to_category": part_to_category,
    }
    return sorting_profile, len(part_to_category), skipped_count, combined_counts


def validateGroupCoverage(
    input_path: Path,
    category_to_combined: dict[int, str],
    category_names: dict[int, str],
) -> None:
    with input_path.open("r") as f:
        data = json.load(f)

    pieces = data.get("pieces")
    if not isinstance(pieces, list):
        raise ValueError("input json missing pieces list")

    used_categories = {
        int(part["category_id"])
        for part in pieces
        if isinstance(part, dict) and part.get("category_id") is not None
    }
    missing_categories = sorted(used_categories - set(category_to_combined.keys()))
    if missing_categories:
        missing_text = ", ".join(
            f"{category_id}:{category_names.get(category_id, 'UNKNOWN')}"
            for category_id in missing_categories
        )
        raise ValueError(f"missing category groups for ids: {missing_text}")


def main() -> int:
    parser = mkParser()
    args = parser.parse_args()

    default_input_path, default_categories_path, default_output_path = getDefaultPaths()
    input_path = Path(args.input_path) if args.input_path else default_input_path
    categories_path = Path(args.categories_path) if args.categories_path else default_categories_path
    output_path = Path(args.output_path) if args.output_path else default_output_path

    category_to_combined = mkCombinedCategoryMap()
    category_names = loadBricklinkCategoryNames(categories_path)
    validateGroupCoverage(input_path, category_to_combined, category_names)
    sorting_profile, mapped_count, skipped_count, combined_counts = buildSortingProfile(
        input_path,
        category_to_combined,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(sorting_profile, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"wrote {output_path}")
    print(f"mapped_parts={mapped_count}")
    print(f"skipped_parts={skipped_count}")
    print(f"combined_categories={len(combined_counts)}")

    top_groups = combined_counts.most_common()
    for combined_category_id, count in top_groups:
        category_names_for_group = [
            category_names.get(int(category_id), "UNKNOWN")
            for category_id in combined_category_id.split("-")
        ]
        names_text = " | ".join(category_names_for_group)
        print(f"{count}\t{combined_category_id}\t{names_text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
