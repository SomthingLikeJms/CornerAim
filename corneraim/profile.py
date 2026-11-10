import json
import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from pathlib import Path
from statistics import median

from corneraim.drill import DEFAULT_DIFFICULTY, DIFFICULTIES, MODES, Result, p90
from corneraim.sens import Sensitivity


@dataclass(frozen=True)
class Profile:
    game_dpi: float = 800
    game_sens: float = 0.4
    seconds: int = 30
    mode: str = "microflick"
    stealth: bool = False
    focus_level: int = 1
    difficulty: str = DEFAULT_DIFFICULTY

    def __post_init__(self) -> None:
        if not all(isfinite(value) and value > 0 for value in (self.game_dpi, self.game_sens)):
            raise ValueError("游戏 DPI 和灵敏度必须是正数")
        if type(self.seconds) is not int or not 5 <= self.seconds <= 300:
            raise ValueError("局长须为 5 到 300 的整数")
        if self.mode not in MODES:
            raise ValueError("未知训练模式")
        if not isinstance(self.difficulty, str) or self.difficulty not in DIFFICULTIES:
            raise ValueError("未知靶球难度")
        if type(self.stealth) is not bool:
            raise ValueError("无效的显示模式")
        if type(self.focus_level) is not int or self.focus_level not in (0, 1, 2):
            raise ValueError("无效的摸鱼底色")
        self.sensitivity

    @property
    def sensitivity(self) -> Sensitivity:
        return Sensitivity(self.game_dpi * self.game_sens, self.game_dpi)


@dataclass(frozen=True)
class HistoryRow:
    played_at: str
    mode: str
    seconds: float
    result: Result
    difficulty: str = DEFAULT_DIFFICULTY


@dataclass(frozen=True)
class PersonalStats:
    rounds: int = 0
    seconds: float = 0.0
    hits: int = 0
    shots: int = 0
    samples: int = 0
    median_ms: float | None = None
    p90_ms: float | None = None
    best_ms: float | None = None
    false_starts: int = 0
    timeouts: int = 0

    @property
    def hits_per_minute(self) -> float:
        return self.hits * 60 / self.seconds if self.seconds else 0.0


def _details(raw: str | None) -> tuple[tuple[float, ...], int, int, str]:
    if raw is None:
        return (), 0, 0, DEFAULT_DIFFICULTY
    detail = json.loads(raw)
    return (tuple(detail["samples_ms"]), detail["false_starts"], detail["timeouts"],
            detail.get("difficulty", DEFAULT_DIFFICULTY))


class LocalStore:
    def __init__(self, directory: Path) -> None:
        self.path = directory / "corneraim.sqlite3"

    @classmethod
    def for_user(cls) -> "LocalStore":
        appdata = os.environ.get("APPDATA")
        directory = Path(appdata) / "CornerAim" if appdata else Path.home() / ".corneraim"
        return cls(directory)

    @contextmanager
    def _connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=0.5)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, "
                "played_at TEXT NOT NULL, mode TEXT NOT NULL, seconds REAL NOT NULL, "
                "hits INTEGER NOT NULL, shots INTEGER NOT NULL, median_ms REAL)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS history_metrics (history_id INTEGER PRIMARY KEY, detail TEXT NOT NULL)")
            yield db

    def load_profile(self) -> Profile:
        if not self.path.is_file():
            return Profile()
        try:
            with self._connection() as db:
                rows = dict(db.execute("SELECT id, value FROM profile WHERE id IN (1, 2, 3)"))
            if 1 not in rows:
                return Profile()
            values = json.loads(rows[1])
            values.pop("office_cpi", None)
            if 2 in rows:
                values["focus_level"] = json.loads(rows[2])
            if 3 in rows:
                values["difficulty"] = json.loads(rows[3])
            return Profile(**values)
        except (OSError, sqlite3.Error, TypeError, ValueError, AttributeError):
            return Profile()

    def save_profile(self, profile: Profile) -> None:
        values = asdict(profile)
        # Keep added preferences separate so earlier builds can still read row 1.
        focus_level = values.pop("focus_level")
        difficulty = values.pop("difficulty")
        with self._connection() as db:
            db.executemany(
                "INSERT INTO profile VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET value = excluded.value",
                ((1, json.dumps(values)), (2, json.dumps(focus_level)), (3, json.dumps(difficulty))),
            )

    def record(self, mode: str, seconds: float, result: Result, *, difficulty: str = DEFAULT_DIFFICULTY) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection() as db:
            row = db.execute(
                "INSERT INTO history(played_at, mode, seconds, hits, shots, median_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, mode, seconds, result.hits, result.shots, result.median_ms),
            )
            detail = dict(samples_ms=result.samples_ms, false_starts=result.false_starts, timeouts=result.timeouts,
                          difficulty=difficulty)
            db.execute("INSERT INTO history_metrics VALUES (?, ?)", (row.lastrowid, json.dumps(detail)))

    def history(self, *, offset: int, limit: int) -> list[HistoryRow]:
        if not self.path.is_file():
            return []
        with self._connection() as db:
            rows = db.execute(
                "SELECT h.played_at, h.mode, h.seconds, h.hits, h.shots, h.median_ms, m.detail "
                "FROM history h LEFT JOIN history_metrics m ON m.history_id=h.id "
                "ORDER BY h.id DESC LIMIT ? OFFSET ?", (limit, offset),
            ).fetchall()
        history = []
        for at, mode, seconds, hits, shots, timing, raw in rows:
            samples, early, late, difficulty = _details(raw)
            history.append(HistoryRow(at, mode, seconds, Result(hits, shots, timing, samples, early, late), difficulty))
        return history

    def statistics(self, mode: str, *, difficulty: str | None = None) -> PersonalStats:
        if not self.path.is_file():
            return PersonalStats()
        rounds = hits = shots = false_starts = timeouts = 0
        seconds = 0.0
        samples = []
        with self._connection() as db:
            rows = db.execute(
                "SELECT h.seconds, h.hits, h.shots, m.detail FROM history h "
                "LEFT JOIN history_metrics m ON m.history_id=h.id WHERE h.mode=?", (mode,),
            )
            for duration, landed, fired, raw in rows:
                timings, early, late, level = _details(raw)
                if difficulty is not None and level != difficulty:
                    continue
                rounds += 1
                seconds += duration
                hits += landed
                shots += fired
                samples.extend(timings)
                false_starts += early
                timeouts += late
        return PersonalStats(rounds, seconds, hits, shots, len(samples), median(samples) if samples else None,
                             p90(samples), min(samples) if samples else None, false_starts, timeouts)
