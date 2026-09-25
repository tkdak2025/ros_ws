"""공통 시퀀스가 호출자에게 반환하는 성공 여부와 근거."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any



@dataclass(frozen=True)
class SequenceResult:
    """공통 시퀀스가 호출자에게 반환하는 성공 여부와 근거."""

    success: bool
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
