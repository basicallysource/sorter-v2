from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from subsystems.classification.carousel import Carousel


class SharedVariables:
    def __init__(self):
        self.classification_ready: bool = True
        self.distribution_ready: bool = True
        self.carousel: Optional["Carousel"] = None
        self.chute_move_in_progress: bool = False
