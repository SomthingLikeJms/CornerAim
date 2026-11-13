from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from math import ceil, copysign, cos, hypot, pi, radians, sin, sqrt, tan, tau
from random import Random
from statistics import median

from corneraim.camera import PITCH_LIMIT, Camera, Vector, direction, dot

COUNTDOWN = 1.5
TARGET_RADIUS = 0.65
RECOVERY_ALIGNMENT = cos(radians(10))
RECOVERY_DELAY = 0.4
HIT_FLASH = 0.09
REACTION_MIN = 0.08
REACTION_LIMIT = 1.5
GRID_SLOTS = tuple((x * 2.7, y * 2.7) for y in (-1, 0, 1) for x in (-2, -1, 0, 1, 2))
GRID_REFILL_ALIGNMENT = cos(radians(4.5))
TRACKING_AREA_RADIUS = 4.5
TRACKING_SPEEDS = {"easy": 5.0, "medium": 8.0, "hard": 11.0}
TRACKING_MAX_SAMPLE_INTERVAL = 0.1


@dataclass(frozen=True)
class Mode:
    name: str
    short: str
    description: str
    radius: float
    timing: str


MODES = {
    "microflick": Mode("单球微调", "单球", "单球近距点射", TARGET_RADIUS, "上靶"),
    "headline": Mode("爆头线微调", "爆头线", "同一高度左右微调", 0.55, "上靶"),
    "gridshot": Mode("三球微调", "三球", "三靶并存，命中补位", 0.78, "连击"),
    "reaction": Mode("视觉反应", "反应", "随机亮球，见球即点", 1.15, "反应"),
    "tracking": Mode("微调跟枪", "跟枪", "准星贴住移动小球", 0.9, ""),
}

DEFAULT_DIFFICULTY = "medium"


@dataclass(frozen=True)
class Difficulty:
    name: str
    scale: float


DIFFICULTIES = {
    "easy": Difficulty("简单", 1.2),
    "medium": Difficulty("中等", 1.0),
    "hard": Difficulty("困难", 0.8),
}


@dataclass(frozen=True)
class Target:
    direction: Vector
    spawned_at: float
    slot: int | None = None


def p90(samples: tuple[float, ...] | list[float]) -> float | None:
    return sorted(samples)[ceil(len(samples) * 0.9) - 1] if samples else None


@dataclass(frozen=True)
class TrackingScore:
    on_target_seconds: float
    seconds: float

    @property
    def ratio(self) -> float:
        return min(1.0, self.on_target_seconds / self.seconds) if self.seconds else 0.0

    @property
    def points(self) -> int:
        return round(self.on_target_seconds * 100)


@dataclass(frozen=True)
class Result:
    hits: int
    shots: int
    median_ms: float | None
    samples_ms: tuple[float, ...] = ()
    false_starts: int = 0
    timeouts: int = 0
    tracking: TrackingScore | None = None

    @property
    def accuracy(self) -> float:
        return self.hits / self.shots if self.shots else 0.0


class Drill(ABC):
    def __init__(
        self, now: float, duration: float, degrees_per_count: float, rng: Random | None, mode: str,
        difficulty: str,
    ) -> None:
        self.starts_at = now + COUNTDOWN
        self.ends_at = self.starts_at + duration
        self.duration = duration
        self.degrees_per_count = degrees_per_count
        self.rng = rng if rng is not None else Random()
        self.mode = mode
        self.difficulty = difficulty
        mode_rules = MODES[mode]
        self.rules = replace(mode_rules, radius=mode_rules.radius * DIFFICULTIES[difficulty].scale)
        self.hit_alignment = cos(radians(self.rules.radius))
        self.camera = Camera()
        self.targets: tuple[Target, ...] = ()
        self.last_hit: tuple[Vector, float] | None = None
        self.lost_since: float | None = None
        self.shots = 0
        self.hit_times: list[float] = []
        self.false_starts = 0
        self.timeouts = 0

    def active(self, now: float) -> bool:
        return self.starts_at <= now < self.ends_at

    def move(self, dx: int, dy: int, now: float) -> None:
        if self.active(now):
            self.camera.move(dx, dy, self.degrees_per_count)

    @abstractmethod
    def update(self, now: float) -> None:
        ...

    @abstractmethod
    def fire(self, now: float) -> None:
        ...

    def presented(self, now: float) -> None:
        pass

    def resume(self, now: float) -> None:
        pass

    def settle_score(self, now: float) -> None:
        pass

    def result(self) -> Result:
        samples = tuple(self.hit_times)
        return Result(len(samples), self.shots, median(samples) if samples else None,
                      samples, self.false_starts, self.timeouts)

    def lost(self, now: float) -> bool:
        forward = self.camera.forward
        if any(dot(forward, target.direction) >= RECOVERY_ALIGNMENT for target in self.targets):
            self.lost_since = None
        elif self.lost_since is None:
            self.lost_since = now
        return self.lost_since is not None and now - self.lost_since >= RECOVERY_DELAY


class Microflick(Drill):
    def __init__(
        self, now: float, duration: float, degrees_per_count: float, rng: Random | None = None,
        *, mode: str = "microflick", difficulty: str = DEFAULT_DIFFICULTY,
    ) -> None:
        super().__init__(now, duration, degrees_per_count, rng, mode, difficulty)
        self.headline_pitch = 0.0

    @property
    def target(self) -> Target | None:
        return self.targets[0] if self.targets else None

    def _spawn(self, now: float) -> None:
        headline = self.mode == "headline"
        horizontal = self.rng.choice((-1, 1)) * self.rng.uniform(1.5, 4.0 if headline else 4.5)
        height = 0.2 if headline else 1.2
        vertical = self.rng.uniform(-height, height)
        target_pitch = self.camera.pitch + vertical
        if headline:
            if abs(self.camera.pitch - self.headline_pitch) > 1.2:
                self.headline_pitch = self.camera.pitch
            target_pitch = self.headline_pitch + vertical
        # Near the poles yaw barely moves the crosshair. An inward pitch offset
        # keeps the target reachable and prevents it from spawning on the crosshair.
        if abs(self.camera.pitch) > 60:
            target_pitch = self.camera.pitch - copysign(self.rng.uniform(0.85, 1.2), self.camera.pitch)
        target_direction = direction(self.camera.yaw + horizontal, target_pitch)
        self.targets = (Target(target_direction, now),)
        self.lost_since = None

    def update(self, now: float) -> None:
        if self.active(now) and (not self.targets or self.lost(now)):
            self._spawn(now)

    def fire(self, now: float) -> None:
        target = self.target
        if target is None or not self.active(now):
            return
        self.shots += 1
        if dot(self.camera.forward, target.direction) >= self.hit_alignment:
            self.hit_times.append((now - target.spawned_at) * 1000)
            self.last_hit = target.direction, now
            self._spawn(now)


class Gridshot(Drill):
    def __init__(
        self, now: float, duration: float, degrees_per_count: float, rng: Random | None = None,
        *, difficulty: str = DEFAULT_DIFFICULTY,
    ) -> None:
        super().__init__(now, duration, degrees_per_count, rng, "gridshot", difficulty)
        self.field: tuple[Vector, ...] = ()
        self.last_score_at: float | None = None

    def _available(self, origin: Vector) -> list[int]:
        occupied = {target.slot for target in self.targets}
        away = cos(radians(1.4))
        return [i for i, vector in enumerate(self.field)
                if i not in occupied and dot(origin, vector) < away]

    def _spawn_field(self, now: float) -> None:
        yaw = self.camera.yaw
        pitch = max(-84.0, min(84.0, self.camera.pitch))
        forward, right, up = direction(yaw, pitch), direction(yaw + 90, 0), direction(yaw, pitch + 90)
        field = []
        for x, y in GRID_SLOTS:
            dx = tan(radians(x + self.rng.uniform(-0.2, 0.2)))
            dy = tan(radians(y + self.rng.uniform(-0.2, 0.2)))
            a, b, c = (f + dx * r + dy * u for f, r, u in zip(forward, right, up))
            length = sqrt(a * a + b * b + c * c)
            field.append((a / length, b / length, c / length))
        self.field = tuple(field)
        self.targets = ()
        slots = self.rng.sample(self._available(self.camera.forward), 3)
        self.targets = tuple(Target(self.field[i], now, i) for i in slots)
        self.lost_since = None

    def update(self, now: float) -> None:
        if self.active(now) and (not self.targets or self.lost(now)):
            self._spawn_field(now)

    def fire(self, now: float) -> None:
        if not self.targets or not self.active(now):
            return
        self.shots += 1
        forward = self.camera.forward
        for i, target in enumerate(self.targets):
            if dot(forward, target.direction) >= self.hit_alignment:
                previous = self.last_score_at if self.last_score_at is not None else target.spawned_at
                self.hit_times.append((now - previous) * 1000)
                self.last_score_at = now
                self.last_hit = target.direction, now
                # A hit at the edge of a larger ball uses the same refill slots as a center hit.
                available = self._available(target.direction)
                nearby = [slot for slot in available
                          if dot(target.direction, self.field[slot]) >= GRID_REFILL_ALIGNMENT]
                if nearby:
                    slot = self.rng.choice(nearby)
                else:
                    slot = max(available, key=lambda candidate: dot(target.direction, self.field[candidate]))
                replacement = Target(self.field[slot], now, slot)
                self.targets = self.targets[:i] + (replacement,) + self.targets[i + 1:]
                return


class ReactionTest(Drill):
    def __init__(
        self, now: float, duration: float, degrees_per_count: float, rng: Random | None = None,
        *, difficulty: str = DEFAULT_DIFFICULTY,
    ) -> None:
        super().__init__(now, duration, degrees_per_count, rng, "reaction", difficulty)
        self._schedule(self.starts_at)

    def _schedule(self, now: float) -> None:
        self.targets = ()
        self.cue_at = now + self.rng.uniform(0.8, 2.0)
        self.shown_at: float | None = None

    def move(self, dx: int, dy: int, now: float) -> None:
        pass

    def resume(self, now: float) -> None:
        self._schedule(max(now, self.starts_at))

    def update(self, now: float) -> None:
        if not self.active(now):
            return
        if self.shown_at is not None and now - self.shown_at > REACTION_LIMIT:
            self.timeouts += 1
            self._schedule(now)
        elif not self.targets and now >= self.cue_at:
            self.targets = (Target(self.camera.forward, now),)

    def presented(self, now: float) -> None:
        if self.targets and self.shown_at is None:
            self.shown_at = now

    def fire(self, now: float) -> None:
        if not self.active(now):
            return
        self.shots += 1
        elapsed = now - self.shown_at if self.shown_at is not None else 0.0
        if elapsed < REACTION_MIN:
            self.false_starts += 1
        elif elapsed > REACTION_LIMIT:
            self.timeouts += 1
        else:
            self.hit_times.append(elapsed * 1000)
        self._schedule(now)


class Tracking(Drill):
    def __init__(
        self, now: float, duration: float, degrees_per_count: float, rng: Random | None = None,
        *, difficulty: str = DEFAULT_DIFFICULTY,
    ) -> None:
        super().__init__(now, duration, degrees_per_count, rng, "tracking", difficulty)
        self.on_target = False
        self.on_target_seconds = 0.0
        self.sample_at = self.starts_at

    @property
    def score(self) -> TrackingScore:
        elapsed = min(self.duration, self.sample_at - self.starts_at)
        return TrackingScore(min(self.on_target_seconds, elapsed), elapsed)

    def _random_point(self, inner_radius: float = 0.0) -> tuple[float, float]:
        radius = sqrt(self.rng.uniform(inner_radius ** 2, TRACKING_AREA_RADIUS ** 2))
        angle = self.rng.uniform(0, tau)
        return radius * cos(angle), radius * sin(angle)

    def _begin_path(self, now: float) -> None:
        yaw = self.camera.yaw
        pitch_limit = PITCH_LIMIT - TRACKING_AREA_RADIUS
        pitch = max(-pitch_limit, min(pitch_limit, self.camera.pitch))
        self.path_basis = direction(yaw, pitch), direction(yaw + 90, 0), direction(yaw, pitch + 90)
        self.path_started_at = now
        self.destination = self._random_point(inner_radius=2.0)
        self._next_segment(now)
        self.lost_since = None

    def _next_segment(self, now: float) -> None:
        start_x, start_y = self.destination
        while True:
            x, y = self._random_point()
            length = hypot(x - start_x, y - start_y)
            if length >= 1.8:
                break
        self.segment_origin = self.destination
        self.destination = x, y
        self.segment_started_at = now
        self.segment_ends_at = now + length / TRACKING_SPEEDS[self.difficulty]

    def _target_at(self, now: float) -> Target:
        # Use the scheduled arrival times even if a frame skips a waypoint.
        while now >= self.segment_ends_at:
            self._next_segment(self.segment_ends_at)
        progress = (now - self.segment_started_at) / (self.segment_ends_at - self.segment_started_at)
        if self.difficulty == "hard":
            progress = (1 - cos(pi * progress)) / 2
        start_x, start_y = self.segment_origin
        end_x, end_y = self.destination
        x = tan(radians(start_x + (end_x - start_x) * progress))
        y = tan(radians(start_y + (end_y - start_y) * progress))
        a, b, c = (forward + x * right + y * up for forward, right, up in zip(*self.path_basis))
        length = sqrt(1 + x * x + y * y)
        return Target((a / length, b / length, c / length), self.path_started_at)

    def settle_score(self, now: float) -> None:
        until = min(now, self.ends_at)
        if until <= self.sample_at:
            return
        # A stalled frame cannot establish that the player tracked the ball throughout the gap.
        if self.on_target:
            self.on_target_seconds += min(until - self.sample_at, TRACKING_MAX_SAMPLE_INTERVAL)
        self.sample_at = until

    def update(self, now: float) -> None:
        self.settle_score(now)
        if not self.active(now):
            return
        if not self.targets:
            self._begin_path(now)
        target = self._target_at(now)
        self.targets = (target,)
        if self.lost(now):
            self._begin_path(now)
            target = self._target_at(now)
            self.targets = (target,)
        self.on_target = dot(self.camera.forward, target.direction) >= self.hit_alignment

    def fire(self, now: float) -> None:
        pass

    def result(self) -> Result:
        return Result(0, 0, None, tracking=self.score)


def start_drill(
    mode: str, now: float, seconds: float, degrees_per_count: float,
    *, difficulty: str = DEFAULT_DIFFICULTY,
) -> Drill:
    if mode == "gridshot":
        return Gridshot(now, seconds, degrees_per_count, difficulty=difficulty)
    if mode == "reaction":
        return ReactionTest(now, seconds, degrees_per_count, difficulty=difficulty)
    if mode == "tracking":
        return Tracking(now, seconds, degrees_per_count, difficulty=difficulty)
    return Microflick(now, seconds, degrees_per_count, mode=mode, difficulty=difficulty)
