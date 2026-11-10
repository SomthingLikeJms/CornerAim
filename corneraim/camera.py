from dataclasses import dataclass
from math import cos, radians, sin, tan

Vector = tuple[float, float, float]
PITCH_LIMIT = 89.0


def dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def direction(yaw: float, pitch: float) -> Vector:
    y, p = radians(yaw), radians(pitch)
    return cos(p) * sin(y), sin(p), cos(p) * cos(y)


@dataclass
class Camera:
    yaw: float = 0.0
    pitch: float = 0.0

    @property
    def forward(self) -> Vector:
        return direction(self.yaw, self.pitch)

    def move(self, dx: int, dy: int, degrees_per_count: float) -> None:
        self.yaw = (self.yaw + dx * degrees_per_count) % 360.0
        self.pitch = max(
            -PITCH_LIMIT, min(PITCH_LIMIT, self.pitch - dy * degrees_per_count)
        )


class View:
    def __init__(
        self, camera: Camera, size: tuple[int, int], hfov: float, *,
        min_vfov: float | None = None, reference_size: tuple[int, int] | None = None,
    ) -> None:
        self.cx, self.cy = size[0] // 2, size[1] // 2
        width, height = reference_size if reference_size is not None else size
        self.focal_length = (width / 2) / tan(radians(hfov / 2))
        if min_vfov is not None:
            self.focal_length = min(self.focal_length, (height / 2) / tan(radians(min_vfov / 2)))
        self.forward = camera.forward
        self.right = direction(camera.yaw + 90, 0)
        self.up = direction(camera.yaw, camera.pitch + 90)

    def project(self, vector: Vector, near: float = 0.0) -> tuple[float, float, float] | None:
        depth = dot(vector, self.forward)
        if depth <= near:
            return None
        scale = self.focal_length / depth
        return self.cx + scale * dot(vector, self.right), self.cy - scale * dot(vector, self.up), depth

    def radius(self, degrees: float, depth: float) -> int:
        return max(1, round(self.focal_length * tan(radians(degrees)) / depth))
