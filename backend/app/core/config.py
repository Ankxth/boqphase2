"""App settings loaded from environment variables (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()

# Which LLM backend to use -- "ollama" (local) or "groq" (API).
# Both configs below can coexist in .env; only the one matching
# LLM_PROVIDER is actually used at call time.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

DATABASE_URL = os.getenv("DATABASE_URL", "")