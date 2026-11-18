
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# Configure how the MCP client launches the server
server_params = StdioServerParameters(
    command=sys.executable,
    args=["app/mcp_server/server.py"],
    env={**os.environ, "PYTHONPATH": "."}
)


async def main():

    # Connect to the MCP server using STDIO
    async with stdio_client(server_params) as (read_stream, write_stream):

        async with ClientSession(read_stream, write_stream) as session:

            # Initialize MCP connection
            await session.initialize()

            print("\nConnected to PlaceExplorer MCP Server!")

            # Discover available tools
            tools = await session.list_tools()

            print("\nAvailable MCP Tools:")

            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")

            # Call the search_places tool
            print("\nCalling search_places...")

            result = await session.call_tool(
                "search_places",
                arguments={
                    "latitude": 18.5204,
                    "longitude": 73.8567,
                    "radius_km": 5,
                    "category": "temples_and_spiritual"
                }
            )

            print("\nTool Response:")
            print(result.content)


if __name__ == "__main__":
    asyncio.run(main())
