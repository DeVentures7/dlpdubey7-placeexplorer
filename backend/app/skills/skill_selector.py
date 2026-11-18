
# Available skills and their matching keywords.

SKILL_REGISTRY = {
    "restaurant_discovery": [
        "restaurant",
        "restaurants",
        "food",
        "dining",
        "dinner",
        "lunch",
        "breakfast",
        "cafe",
        "coffee",
        "eat",
        "eating",
        "romantic",
        "outdoor seating",
        "fine dining",
    ]
}


def select_skills(message: str) -> list[str]:
    """
    Select relevant skills based on the user's message.
    """

    message = message.lower()

    selected_skills = []

    for skill_name, keywords in SKILL_REGISTRY.items():

        if any(keyword in message for keyword in keywords):
            selected_skills.append(skill_name)

    return selected_skills
