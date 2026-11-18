import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

print("Calling Gemini...")

response = client.models.generate_content(
    model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
    contents="Say hello in one sentence."
)

print("Gemini response:")
print(response.text)