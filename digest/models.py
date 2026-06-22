from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Article:
    id: str
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str
    query: str = ""
    score: float = 0.0
    source_home: str = ""
    is_chint_russia: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["published_at"] = self.published_at.isoformat()
        return result
