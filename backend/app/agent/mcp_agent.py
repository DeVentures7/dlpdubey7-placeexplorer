import asyncio
import json
import os
import sys

from google.genai import types

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.skills.skill_selector import select_skills
from app.skills.skill_loader import load_skill
from app.skills.intent_router import select_information_sources

from app.rag.rag_pipeline import retrieve_context


# Configure how the MCP client launches the server.
SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["app/mcp_server/server.py"],
    env={**os.environ, "PYTHONPATH": "."}
)


# Convert MCP tool definitions into Gemini function declarations.
def convert_mcp_tools_to_gemini(mcp_tools):

    function_declarations = []

    for tool in mcp_tools:

        declaration = types.FunctionDeclaration(
            name=tool.name,
            description=tool.description or "",
            parameters_json_schema=tool.inputSchema
        )

        function_declarations.append(declaration)

    return types.Tool(
        function_declarations=function_declarations
    )


# Extract the MCP tool response.
def extract_tool_result(result):

    if result.isError:
        return {"error": "MCP tool execution failed"}

    text_parts = [
        item.text
        for item in result.content
        if hasattr(item, "text")
    ]

    if len(text_parts) == 1:

        try:
            return json.loads(text_parts[0])

        except json.JSONDecodeError:
            return {"result": text_parts[0]}

    return {"result": text_parts}


# Run the Gemini Agent using RAG and MCP tools.
async def run_agent(message: str, client, model: str):

    # STEP 1: Identify relevant skills.
    selected_skills = select_skills(message)

    skill_instructions = [
        load_skill(skill_name)
        for skill_name in selected_skills
    ]

    combined_skill_instructions = "\n\n".join(
        skill_instructions
    )

    # STEP 2: Decide which information sources are required.
    sources = select_information_sources(message)

    use_rag = sources["use_rag"]
    use_mcp = sources["use_mcp"]

    print("\n--- INTENT ROUTING ---")
    print("RAG enabled:", use_rag)
    print("MCP enabled:", use_mcp)

    # STEP 3: Retrieve context only when RAG is required.
    rag_context = ""

    if use_rag:

        print("\n--- RAG RETRIEVAL ---")

        try:
            rag_context = await asyncio.to_thread(
                retrieve_context,
                message,
                client,
                top_k=3
            )

            print("RAG context retrieved.")

        except Exception as error:
            print("RAG retrieval failed:", error)

    # STEP 4: Prepare Gemini instructions.
    system_instruction = (
        "You are PlaceExplorer, an AI assistant for discovering places.\n\n"

        "You have access to two information sources:\n"
        "1. RAG: Stored destination knowledge.\n"
        "2. MCP: Live place discovery and information.\n\n"

        "Rules:\n"
        "- Use RAG context for relevant destination knowledge.\n"
        "- Use MCP tools for current place information.\n"
        "- Do not treat RAG information as live information.\n"
        "- Never invent place information.\n"
        "- If information is unavailable, clearly mention that.\n"
        "- Combine RAG knowledge and MCP results when both are relevant.\n\n"

        "Retrieved Knowledge Context:\n"
        + (rag_context or "No relevant knowledge was retrieved.")
        + "\n\n"

        "Follow these task-specific instructions:\n\n"
        + combined_skill_instructions
    )

    # STEP 5: Handle RAG-only requests.
    # Do not launch the MCP server for these requests.
    if not use_mcp:

        print("\n--- RAG-ONLY EXECUTION ---")

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3
            )
        )

        return response.text or "I couldn't generate a response."

    # STEP 6: Launch MCP server and establish communication.
    async with stdio_client(SERVER_PARAMS) as (
        read_stream,
        write_stream
    ):

        async with ClientSession(
            read_stream,
            write_stream
        ) as session:

            # Initialize MCP connection.
            await session.initialize()

            # Discover tools exposed by the MCP server.
            mcp_response = await session.list_tools()

            mcp_tools = mcp_response.tools

            # Convert MCP tools into Gemini declarations.
            gemini_tools = convert_mcp_tools_to_gemini(
                mcp_tools
            )

            # Configure Gemini with MCP tools and RAG context.
            config = types.GenerateContentConfig(
                tools=[gemini_tools],
                system_instruction=system_instruction
            )

            # Conversation history.
            contents = [message]

            # STEP 7: Limit iterations to prevent endless tool calling.
            for _ in range(5):

                response = await asyncio.to_thread(
                    client.models.generate_content,
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

                # No function calls means Gemini has produced
                # its final answer.
                if not function_calls:

                    return response.text or "I couldn't generate a response."

                # Preserve Gemini's response in conversation history.
                contents.append(model_content)

                tool_response_parts = []

                # Execute each requested tool through MCP.
                for function_call in function_calls:

                    function_name = function_call.name

                    arguments = dict(
                        function_call.args or {}
                    )

                    # Invoke the MCP tool.
                    mcp_result = await session.call_tool(
                        function_name,
                        arguments=arguments
                    )

                    # Extract the result.
                    result = extract_tool_result(mcp_result)

                    # Prepare response for Gemini.
                    tool_response_parts.append(
                        types.Part.from_function_response(
                            name=function_name,
                            response=result
                        )
                    )

                # Send MCP tool results back to Gemini.
                contents.append(
                    types.Content(
                        role="user",
                        parts=tool_response_parts
                    )
                )

    return "I couldn't complete the request within the allowed tool calls."
