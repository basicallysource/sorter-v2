"""Classification provider selection — which service answers "what mold is
this piece" and "what color is this piece".

Brickognize answers both from one call today; the hosted color model on the
main hive (hive.basically.website, NOT the machine's configured Hive targets)
is an alternative color source. The two choices are independent: mold and
color providers are selected separately in Settings and dispatched separately
by the recognition path, with Brickognize's color kept as the fallback when a
remote color provider fails or times out.

Adding a provider is: new id constant, new spec entry, new dispatch branch in
the recognition path.
"""

from __future__ import annotations

from dataclasses import dataclass


COLOR_PROVIDER_BRICKOGNIZE = "brickognize"
COLOR_PROVIDER_HIVE_BASICALLY = "hive_basically"
MOLD_PROVIDER_BRICKOGNIZE = "brickognize"

DEFAULT_COLOR_PROVIDER = COLOR_PROVIDER_BRICKOGNIZE
DEFAULT_MOLD_PROVIDER = MOLD_PROVIDER_BRICKOGNIZE


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    description: str


COLOR_PROVIDER_SPECS: dict[str, ProviderSpec] = {
    COLOR_PROVIDER_BRICKOGNIZE: ProviderSpec(
        id=COLOR_PROVIDER_BRICKOGNIZE,
        label="Brickognize",
        description="Color from the same Brickognize call that identifies the mold. No extra request.",
    ),
    COLOR_PROVIDER_HIVE_BASICALLY: ProviderSpec(
        id=COLOR_PROVIDER_HIVE_BASICALLY,
        label="basically color model",
        description=(
            "Hosted color model at hive.basically.website (independent of your "
            "configured Hive accounts). The piece's crops are sent to the service "
            "and logged there to improve the model. Falls back to Brickognize's "
            "color if unreachable."
        ),
    ),
}

MOLD_PROVIDER_SPECS: dict[str, ProviderSpec] = {
    MOLD_PROVIDER_BRICKOGNIZE: ProviderSpec(
        id=MOLD_PROVIDER_BRICKOGNIZE,
        label="Brickognize",
        description="Mold identification via api.brickognize.com.",
    ),
}


def normalizeColorProvider(value: object) -> str:
    return value if isinstance(value, str) and value in COLOR_PROVIDER_SPECS else DEFAULT_COLOR_PROVIDER


def normalizeMoldProvider(value: object) -> str:
    return value if isinstance(value, str) and value in MOLD_PROVIDER_SPECS else DEFAULT_MOLD_PROVIDER
