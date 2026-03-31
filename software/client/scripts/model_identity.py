#!/usr/bin/env python3
"""Stable human-friendly identities for trained detector models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path

ADJECTIVES = [
    "amber",
    "ardent",
    "brisk",
    "calm",
    "cedar",
    "clear",
    "cobalt",
    "cosmic",
    "crisp",
    "dapper",
    "ember",
    "even",
    "fable",
    "fern",
    "flint",
    "gentle",
    "golden",
    "granite",
    "harbor",
    "honey",
    "ivory",
    "jasper",
    "keen",
    "kindle",
    "lively",
    "lucent",
    "maple",
    "meadow",
    "merry",
    "misty",
    "noble",
    "opal",
    "pearl",
    "pine",
    "plucky",
    "quiet",
    "rapid",
    "river",
    "rustic",
    "sable",
    "scarlet",
    "silver",
    "spruce",
    "steady",
    "sunny",
    "swift",
    "tidal",
    "umber",
    "vivid",
    "willow",
]

ANIMALS = [
    "badger",
    "beacon",
    "beetle",
    "bison",
    "crane",
    "dingo",
    "falcon",
    "finch",
    "fox",
    "gecko",
    "heron",
    "ibis",
    "jackal",
    "jaguar",
    "kestrel",
    "koala",
    "lemur",
    "lynx",
    "marten",
    "moose",
    "newt",
    "ocelot",
    "orca",
    "otter",
    "owl",
    "panda",
    "panther",
    "parrot",
    "pika",
    "puma",
    "quail",
    "quokka",
    "raven",
    "rook",
    "seal",
    "shark",
    "skylark",
    "stoat",
    "swift",
    "tapir",
    "tern",
    "tiger",
    "viper",
    "walrus",
    "weasel",
    "whale",
    "wolf",
    "wren",
    "yak",
    "zebra",
]


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


def _base36(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value == 0:
        return "0"
    chars: list[str] = []
    while value:
        value, rem = divmod(value, 36)
        chars.append(alphabet[rem])
    return "".join(reversed(chars))


def compute_dataset_fingerprint(dataset_dir: Path) -> str:
    """Hash the key dataset definition files into a short stable fingerprint."""
    digest = hashlib.sha1()
    for rel_path in [
        "annotations/train.json",
        "annotations/val.json",
        "annotations/test.json",
        "dataset.yaml",
    ]:
        path = dataset_dir / rel_path
        if not path.exists():
            continue
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:10]


def collect_dataset_counts(dataset_dir: Path) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for split in ["train", "val", "test"]:
        ann_path = dataset_dir / "annotations" / f"{split}.json"
        if not ann_path.exists():
            continue
        payload = json.loads(ann_path.read_text())
        stats[split] = {
            "images": len(payload.get("images", [])),
            "annotations": len(payload.get("annotations", [])),
            "categories": len(payload.get("categories", [])),
        }
    return stats


@dataclass(frozen=True)
class ModelIdentity:
    model_id: str
    family: str
    base_model: str
    variant: str | None
    imgsz: int | None
    epochs: int | None
    primary_name: str
    technical_name: str
    technical_label: str
    nickname: str
    friendly_name: str
    short_code: str
    display_name: str

    def to_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


def build_model_identity(
    *,
    model_id: str,
    family: str,
    base_model: str,
    dataset_fingerprint: str,
    imgsz: int | None = None,
    epochs: int | None = None,
    variant: str | None = None,
) -> ModelIdentity:
    seed = "|".join(
        [
            model_id,
            family,
            base_model,
            variant or "",
            str(imgsz or ""),
            str(epochs or ""),
            dataset_fingerprint,
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    adjective = ADJECTIVES[int(digest[:8], 16) % len(ADJECTIVES)]
    animal = ANIMALS[int(digest[8:16], 16) % len(ANIMALS)]
    short_suffix = _base36(int(digest[16:22], 16))[-3:]

    technical_bits = [slugify(base_model)]
    if variant:
        technical_bits.append(slugify(variant))
    if imgsz:
        technical_bits.append(str(imgsz))
    technical_name = "-".join(bit for bit in technical_bits if bit)
    technical_label = f"{model_id} {technical_name}"

    nickname = f"{adjective}-{animal}"
    friendly_name = f"{adjective.title()} {animal.title()}"
    short_code = f"{slugify(model_id)}-{short_suffix}"
    primary_name = friendly_name
    display_name = f"{friendly_name} ({technical_label})"

    return ModelIdentity(
        model_id=model_id,
        family=family,
        base_model=base_model,
        variant=variant,
        imgsz=imgsz,
        epochs=epochs,
        primary_name=primary_name,
        technical_name=technical_name,
        technical_label=technical_label,
        nickname=nickname,
        friendly_name=friendly_name,
        short_code=short_code,
        display_name=display_name,
    )
