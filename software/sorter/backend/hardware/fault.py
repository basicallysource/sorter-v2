class HardwareFault(Exception):
    """A hardware problem only the operator can fix, in their terms: a short
    title and a message that says what failed and what to do about it.

    The hardware lifecycle shows it as the machine's error (`hardware_error` in
    `system_status`); any other exception shows as GENERIC_TITLE with its
    text."""

    GENERIC_TITLE = "Hardware error"

    def __init__(self, title: str, message: str):
        super().__init__(message)
        self.title = title
        self.message = message

    @classmethod
    def of(cls, exc: BaseException) -> "HardwareFault":
        return exc if isinstance(exc, cls) else cls(cls.GENERIC_TITLE, str(exc))

    def data(self) -> dict[str, str]:
        return {"title": self.title, "message": self.message}


class NotHomed(HardwareFault):
    """The hardware started, but something did not find home. The machine stays
    started and not homed, with this as the reason, so the part can be moved
    and checked and homing tried again; nothing else is held up."""
