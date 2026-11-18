
from google.genai import types

from app.tools.place_tools import search_places, get_place_details


# 1. Define the Python functions Gemini is allowed to call.
AVAILABLE_FUNCTIONS = {
    "search_places": search_places,
    "get_place_details": get_place_details,
}


# 2. Describe the functions and their parameters to Gemini.
PLACE_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_places",
            description=(
                "Search for places around a coordinate using OpenStreetMap "
                "data. Returns structured place data with id (OSM type/ID), "
                "name, category, latitude, longitude and, when available, "
                "address and opening_hours."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "latitude": {
                        "type": "NUMBER",
                        "description": "Latitude of the search center."
                    },
                    "longitude": {
                        "type": "NUMBER",
                        "description": "Longitude of the search center."
                    },
                    "radius_km": {
                        "type": "NUMBER",
                        "description": "Search radius in kilometres (max 50)."
                    },
                    "category": {
                        "type": "STRING",
                        "description": (
                            "One of: temples_and_spiritual, "
                            "tourist_attractions_and_heritage, "
                            "parks_and_nature, restaurants_and_cafes, "
                            "shopping_and_entertainment."
                        )
                    }
                },
                "required": ["latitude", "longitude", "category"]
            }
        ),
        types.FunctionDeclaration(
            name="get_place_details",
            description=(
                "Get details of a place using its OpenStreetMap ID "
                '(format "<osm_type>/<osm_id>", e.g. "node/123456789"), '
                "as returned by search_places."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "place_id": {
                        "type": "STRING",
                        "description": "OSM place ID, e.g. node/123456789."
                    }
                },
                "required": ["place_id"]
            }
        )
    ]
)


# 3. Run the Gemini Agent.
def run_agent(message: str, client, model: str):

    contents = [message]

    config = types.GenerateContentConfig(
        tools=[PLACE_TOOLS],
        system_instruction=(
            "You are PlaceExplorer, an AI assistant for discovering places. "
            "Use the available functions to search for places and retrieve "
            "their details. Do not invent place information. "
            "Use tool results as the source of truth. Fields that are null "
            "in tool results are genuinely unavailable - say so instead of "
            "guessing."
        )
    )

    # Limit iterations to prevent an endless tool-calling loop.
    for _ in range(5):

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

        candidate = response.candidates[0]
        model_content = candidate.content

        # Find function calls requested by Gemini.
        function_calls = [
            part.function_call
            for part in model_content.parts
            if part.function_call
        ]

        # No function calls means Gemini has produced its final answer.
        if not function_calls:
            return response.text or "I couldn't generate a response."

        # Preserve Gemini's response in the conversation history.
        contents.append(model_content)

        tool_response_parts = []

        # Execute each requested Python function.
        for function_call in function_calls:

            function_name = function_call.name

            arguments = dict(function_call.args or {})

            function = AVAILABLE_FUNCTIONS.get(function_name)

            if function is None:
                result = {"error": f"Unknown function: {function_name}"}
            else:
                result = function(**arguments)

            tool_response_parts.append(
                types.Part.from_function_response(
                    name=function_name,
                    response=result
                )
            )

        # Send Python function results back to Gemini.
        contents.append(
            types.Content(
                role="user",
                parts=tool_response_parts
            )
        )

    return "I couldn't complete the request within the allowed tool calls."
