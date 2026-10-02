"""Display names for catalog ids. A monster's type id ("chaos_warrior")
leaked into the log, the placement lines and the defence prompts
whenever the quest gave it no name of its own -- the owner read
"chaos_warrior defends: 4 dice". Every player-facing string goes
through here; ids stay ids everywhere else."""


def monster_display_name(type_id: str | None) -> str:
    return (type_id or "monster").replace("_", " ").title()


def monster_name(mdef: dict) -> str:
    """The quest's own name for a monster, else its type's display name."""
    return mdef.get("name") or monster_display_name(mdef.get("type"))
