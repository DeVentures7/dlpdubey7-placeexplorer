from pathlib import Path

# Resolve the backend directory
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Knowledge base directory
KNOWLEDGE_BASE_DIR = BACKEND_DIR / "knowledge_base"


def load_documents(directory: Path = KNOWLEDGE_BASE_DIR) -> list[dict]:
    documents = []

    # Find all Markdown and text files
    for file_path in directory.rglob("*"):

        if file_path.is_file() and file_path.suffix.lower() in {".md", ".txt"}:

            content = file_path.read_text(encoding="utf-8").strip()

            if content:
                documents.append({
                    "source": str(file_path.relative_to(directory)),
                    "content": content
                })

    return documents