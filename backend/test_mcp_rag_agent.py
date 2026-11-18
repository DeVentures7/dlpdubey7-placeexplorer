import asyncio
import os

from dotenv import load_dotenv
from google import genai

from app.agent.agent import run_agent


load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


async def main():

    question = "Suggest places in Goa for nightlife."

    response = run_agent(
        message=question,
        client=client,
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    )

    print("\n--- PLACEXPLORER RESPONSE ---")
    print(response)


if __name__ == "__main__":
    asyncio.run(main())