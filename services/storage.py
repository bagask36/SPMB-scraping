from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class State:
    name: str
    rank: Optional[int]
    score: Optional[float]
    last_check: Optional[str]

    @staticmethod
    def empty() -> "State":
        return State(name="", rank=None, score=None, last_check=None)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "State":
        name = str(data.get("name") or "")
        rank_raw = data.get("rank")
        score_raw = data.get("score")
        last_check = data.get("last_check")

        rank = None
        if isinstance(rank_raw, int):
            rank = rank_raw
        elif isinstance(rank_raw, str):
            try:
                rank = int(rank_raw.strip())
            except ValueError:
                rank = None

        score = None
        if isinstance(score_raw, (int, float)):
            score = float(score_raw)
        elif isinstance(score_raw, str):
            try:
                score = float(score_raw.strip().replace(",", "."))
            except ValueError:
                score = None

        if last_check is not None:
            last_check = str(last_check)

        return State(name=name, rank=rank, score=score, last_check=last_check)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rank": self.rank,
            "score": self.score,
            "last_check": self.last_check,
        }


DEFAULT_STATE_PATH = Path("data/state.json")


def load_state(path: Path = DEFAULT_STATE_PATH) -> State:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return State.empty()
        data = json.loads(raw)
        if not isinstance(data, dict):
            return State.empty()
        return State.from_dict(data)
    except FileNotFoundError:
        return State.empty()
    except json.JSONDecodeError:
        return State.empty()


def save_state(state: State, path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload + "\n", encoding="utf-8")
    tmp_path.replace(path)


def isoformat_now(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")
