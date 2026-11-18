
from app.skills.intent_router import select_information_sources


test_queries = [
    "What is Pune famous for?",
    "Find vegetarian restaurants in Pune",
    "Plan a half-day outing in Pune with temples",
    "Tell me the history of Shaniwar Wada",
    "Find the current details of Shaniwar Wada",
    "Plan a full-day trip to Pune with nature and food",
]


for query in test_queries:

    result = select_information_sources(query)

    print("\nQuery:", query)
    print("RAG:", result["use_rag"])
    print("MCP:", result["use_mcp"])
