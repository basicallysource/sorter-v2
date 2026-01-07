from defs.sorter_controller import SorterLifecycle


class SorterController:
    def __init__(self):
        self.state = SorterLifecycle.INITIALIZING

    def start(self) -> None:
        self.state = SorterLifecycle.RUNNING

    def stop(self) -> None:
        self.state = SorterLifecycle.READY
