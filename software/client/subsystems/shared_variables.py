from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from defs.known_object import KnownObject


class SharedVariables:
    def __init__(self):
        self.classification_ready: bool = True
        self.distribution_ready: bool = True
        self.pending_piece: Optional["KnownObject"] = None
