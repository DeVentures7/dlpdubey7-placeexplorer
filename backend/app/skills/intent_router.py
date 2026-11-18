
# Keywords indicating that the user wants to plan an outing or trip.
PLANNING_KEYWORDS = [
    "plan",
    "outing",
    "itinerary",
    "trip",
    "tour",
    "half-day",
    "half day",
    "full-day",
    "full day",
    "day trip",
    "places to visit",
    "sightseeing",
]

# Keywords indicating that the user needs current place information.
LIVE_PLACE_KEYWORDS = [
    "nearby",
    "near me",
    "open now",
    "currently open",
    "live",
    "current",
    "latest",
    "find",
    "search",
    "restaurant",
    "restaurants",
    "cafe",
    "cafes",
    "hotel",
    "hotels",
    "directions",
    "route",
    "distance",
    "travel time",
]

# Keywords indicating that the user needs destination knowledge.
KNOWLEDGE_KEYWORDS = [
    "famous for",
    "history",
    "historical",
    "culture",
    "cultural",
    "heritage",
    "best time to visit",
    "about",
    "popular attractions",
    "tourist attractions",
    "travel guide",
]


def select_information_sources(message: str) -> dict:
    """
    Decide whether a request needs RAG, MCP, or both.
    """

    query = message.lower()

    needs_rag = any(
        keyword in query
        for keyword in KNOWLEDGE_KEYWORDS
    )

    needs_mcp = any(
        keyword in query
        for keyword in LIVE_PLACE_KEYWORDS
    )

    is_planning_request = any(
        keyword in query
        for keyword in PLANNING_KEYWORDS
    )

    # Outing planning needs destination knowledge
    # as well as live place information.
    if is_planning_request:
        needs_rag = True
        needs_mcp = True

    return {
        "use_rag": needs_rag,
        "use_mcp": needs_mcp
    }
