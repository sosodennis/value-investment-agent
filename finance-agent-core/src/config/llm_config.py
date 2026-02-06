import os

# Model Defaults
DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "arcee-ai/trinity-large-preview:free")

# Provider Configs
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"

# Connection Settings
LLM_TIMEOUT = 60
LLM_MAX_RETRIES = 2
