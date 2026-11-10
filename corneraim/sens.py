from dataclasses import dataclass
from math import isfinite

VALORANT_YAW = 0.07
CM360_EDPI = 360 * 2.54 / VALORANT_YAW


@dataclass(frozen=True)
class Sensitivity:
    edpi: float
    dpi: float

    def __post_init__(self) -> None:
        if not all(isfinite(value) and value > 0 for value in (self.edpi, self.dpi)):
            raise ValueError("eDPI 和 DPI 必须是有限正数。")
        if not 0 < self.degrees_per_count <= 5 or not isfinite(self.cm360):
            raise ValueError("这组灵敏度超出 demo 可用范围。")

    @property
    def cm360(self) -> float:
        return CM360_EDPI / self.edpi

    @property
    def degrees_per_count(self) -> float:
        return VALORANT_YAW * self.edpi / self.dpi
