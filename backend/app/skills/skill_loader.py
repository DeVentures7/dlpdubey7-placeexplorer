from pathlib import Path


SKILLS_DIR = Path(__file__).parent


def load_skill(skill_name: str) -> str:
    """
    Load a Skill's instructions from its SKILL.md file.
    """

    skill_file = SKILLS_DIR / skill_name / "SKILL.md"

    if not skill_file.exists():
        raise FileNotFoundError(
            f"Skill not found: {skill_name}"
        )

    return skill_file.read_text(encoding="utf-8")
