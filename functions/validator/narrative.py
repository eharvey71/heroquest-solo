"""Narrative soft checks — warn, never fail. See generator-prompt.md STYLE
and design/quest-generator-design.md section 5 "Narrative".
"""

from __future__ import annotations


def _word_count(text: str) -> int:
    return len(text.split())


def check_narrative(quest: dict) -> list:
    warnings = []

    backstory = quest.get("backstory", "")
    n = _word_count(backstory)
    if not (80 <= n <= 200):
        warnings.append(f"backstory is {n} words, outside the recommended 80-200")

    for room_id, room in quest.get("rooms", {}).items():
        reveal_text = room.get("revealText")
        if reveal_text and _word_count(reveal_text) > 40:
            warnings.append(f"{room_id} revealText is {_word_count(reveal_text)} words, over the 40-word guideline")

    completion_text = quest.get("completionText", "")
    n = _word_count(completion_text)
    if not (40 <= n <= 100):
        warnings.append(f"completionText is {n} words, outside the recommended 40-100")

    return warnings
