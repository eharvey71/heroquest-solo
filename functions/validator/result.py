"""Shared result type. Every check module returns plain lists of
machine-readable strings (so a future retry loop can hand them straight
back to the LLM, per design/quest-generator-design.md section 6); core.py
assembles them into one ValidationResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def fmt_pos(pos) -> str:
    return f"[{pos[0]},{pos[1]}]"
