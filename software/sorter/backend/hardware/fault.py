class HardwareFault(Exception):
    """A hardware problem only the operator can fix, in their terms: a short
    title and a message that says what failed and what to do about it.

    The hardware lifecycle shows it as the machine's error (`hardware_error` in
    `system_status`); any other exception shows as "Hardware error" with its
    text."""

    def __init__(self, title: str, message: str):
        super().__init__(message)
        self.title = title
        self.message = message

    @classmethod
    def of(cls, exc: BaseException) -> "HardwareFault":
        return exc if isinstance(exc, cls) else cls("Hardware error", str(exc))

    def data(self) -> dict[str, str]:
        return {"title": self.title, "message": self.message}
