from dataclasses import dataclass


@dataclass
class FlowEvent:
    index: int
    direction: str  # "s2c" or "c2s"
    data: bytes
    time: float

    @property
    def length(self) -> int:
        return len(self.data)
