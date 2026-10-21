"""Catálogo de proveedores de IA con capa gratuita.

Todos hablan el formato de OpenAI (/chat/completions), así que un solo cliente
sirve para todos. Las listas de modelos son las preferidas; al arrancar, el
router consulta /models de cada proveedor y descarta lo que ya no exista
(los catálogos gratuitos cambian cada pocos meses).

Campos:
  prioridad       menor = se prefiere (calidad + generosidad de la capa gratis)
  llave           variable(s) de entorno con la API key (admite varias separadas por coma)
  sin_llave       funciona sin registrarse
  cuota_por_llave el límite diario es de la cuenta entera, no por modelo
  modelos         [{id, vision?, rapido?}] en orden de preferencia
  patrones_extra  regex para incluir modelos nuevos que aparezcan en /models
"""

CATALOGO = [
    {
        "id": "gemini",
        "nombre": "Google Gemini",
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "llave": "GEMINI_API_KEY",
        "registro": "https://aistudio.google.com/apikey",
        "prioridad": 1,
        "modelos": [
            {"id": "gemini-2.5-flash", "vision": True},
            {"id": "gemini-flash-latest", "vision": True},
            {"id": "gemini-2.5-flash-lite", "vision": True, "rapido": True},
            {"id": "gemini-flash-lite-latest", "vision": True, "rapido": True},
            {"id": "gemini-2.0-flash", "vision": True},
            {"id": "gemini-2.0-flash-lite", "vision": True, "rapido": True},
        ],
        "patrones_extra": [r"^gemini-[3-9][\w.]*-flash(-lite)?(-preview)?$"],
        "vision_extra": True,
        # los Gemini 3.x piensan por defecto y tardan 2–14 s; «low» lo aceptan todos («minimal» no)
        "cuerpo_extra": {"reasoning_effort": "low"},
    },
    {
        "id": "groq",
        "nombre": "Groq",
        "base": "https://api.groq.com/openai/v1",
        "llave": "GROQ_API_KEY",
        "registro": "https://console.groq.com/keys",
        "prioridad": 1,
        "modelos": [
            {"id": "moonshotai/kimi-k2-instruct-0905"},
            {"id": "openai/gpt-oss-120b"},
            {"id": "llama-3.3-70b-versatile"},
            {"id": "qwen/qwen3-32b"},
            {"id": "meta-llama/llama-4-maverick-17b-128e-instruct", "vision": True},
            {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "vision": True, "rapido": True},
            {"id": "openai/gpt-oss-20b", "rapido": True},
            {"id": "llama-3.1-8b-instant", "rapido": True},
        ],
        # Groq renueva su catálogo seguido: adopta solos los Qwen 3.x y Kimi que aparezcan
        "patrones_extra": [r"^qwen/qwen3[\w.-]*$", r"^moonshotai/kimi-k2[\w.-]*$"],
        # rapidísimos pero se confunden con la personalidad y las herramientas: para tareas de fondo
        "rapido_extra": [r"^qwen/"],
        "stt": "whisper-large-v3-turbo",
    },
    {
        "id": "cerebras",
        "nombre": "Cerebras",
        "base": "https://api.cerebras.ai/v1",
        "llave": "CEREBRAS_API_KEY",
        "registro": "https://cloud.cerebras.ai",
        "prioridad": 2,
        "modelos": [
            {"id": "gpt-oss-120b"},
            {"id": "qwen-3-235b-a22b-instruct-2507"},
            {"id": "zai-glm-4.6"},
            {"id": "llama-3.3-70b"},
            {"id": "qwen-3-32b"},
            {"id": "llama3.1-8b", "rapido": True},
        ],
    },
    {
        "id": "mistral",
        "nombre": "Mistral",
        "base": "https://api.mistral.ai/v1",
        "llave": "MISTRAL_API_KEY",
        "registro": "https://console.mistral.ai/api-keys",
        "prioridad": 2,
        "modelos": [
            {"id": "mistral-medium-latest", "vision": True},
            {"id": "mistral-large-latest"},
            {"id": "mistral-small-latest", "vision": True, "rapido": True},
            {"id": "open-mistral-nemo", "rapido": True},
        ],
    },
    {
        "id": "github",
        "nombre": "GitHub Models",
        "base": "https://models.github.ai/inference",
        "lista_url": "https://models.github.ai/catalog/models",
        "llave": "GITHUB_TOKEN",
        "registro": "https://github.com/settings/personal-access-tokens/new",
        "prioridad": 2,
        "modelos": [
            {"id": "openai/gpt-4.1", "vision": True},
            {"id": "openai/gpt-4o", "vision": True},
            {"id": "deepseek/DeepSeek-V3-0324"},
            {"id": "openai/gpt-4.1-mini", "vision": True, "rapido": True},
            {"id": "openai/gpt-4o-mini", "vision": True, "rapido": True},
        ],
    },
    {
        "id": "openrouter",
        "nombre": "OpenRouter (gratis)",
        "base": "https://openrouter.ai/api/v1",
        "llave": "OPENROUTER_API_KEY",
        "registro": "https://openrouter.ai/settings/keys",
        "prioridad": 3,
        "cuota_por_llave": True,
        "modelos": [],  # se descubren solos: todos los ':free' del momento
        "cabeceras": {"HTTP-Referer": "http://localhost", "X-Title": "JARVIS local"},
    },
    {
        "id": "nvidia",
        "nombre": "NVIDIA NIM",
        "base": "https://integrate.api.nvidia.com/v1",
        "llave": "NVIDIA_API_KEY",
        "registro": "https://build.nvidia.com",
        "prioridad": 3,
        "cuerpo_extra": {"max_tokens": 4096},
        "modelos": [
            {"id": "moonshotai/kimi-k2-instruct-0905"},
            {"id": "deepseek-ai/deepseek-v3.1"},
            {"id": "qwen/qwen3-235b-a22b"},
            {"id": "meta/llama-3.3-70b-instruct"},
            {"id": "meta/llama-4-maverick-17b-128e-instruct", "vision": True},
            {"id": "meta/llama-3.1-8b-instruct", "rapido": True},
        ],
    },
    {
        "id": "sambanova",
        "nombre": "SambaNova",
        "base": "https://api.sambanova.ai/v1",
        "llave": "SAMBANOVA_API_KEY",
        "registro": "https://cloud.sambanova.ai/apis",
        "prioridad": 4,
        "cuota_por_llave": True,
        "modelos": [
            {"id": "DeepSeek-V3.1"},
            {"id": "Meta-Llama-3.3-70B-Instruct"},
            {"id": "Llama-4-Maverick-17B-128E-Instruct", "vision": True},
            {"id": "Meta-Llama-3.1-8B-Instruct", "rapido": True},
        ],
    },
    {
        "id": "cohere",
        "nombre": "Cohere",
        "base": "https://api.cohere.ai/compatibility/v1",
        "llave": "COHERE_API_KEY",
        "registro": "https://dashboard.cohere.com/api-keys",
        "prioridad": 4,
        "cuota_por_llave": True,
        "listar": False,
        "modelos": [
            {"id": "command-a-03-2025"},
            {"id": "command-a-vision-07-2025", "vision": True},
            {"id": "command-r7b-12-2024", "rapido": True},
        ],
    },
    {
        "id": "cloudflare",
        "nombre": "Cloudflare Workers AI",
        "base": "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        "llave": "CLOUDFLARE_API_TOKEN",
        "registro": "https://dash.cloudflare.com/profile/api-tokens",
        "prioridad": 5,
        "cuota_por_llave": True,
        "listar": False,
        "cuerpo_extra": {"max_tokens": 2048},
        "modelos": [
            {"id": "@cf/openai/gpt-oss-120b"},
            {"id": "@cf/meta/llama-3.3-70b-instruct-fp8-fast"},
            {"id": "@cf/meta/llama-4-scout-17b-16e-instruct", "vision": True},
            {"id": "@cf/meta/llama-3.1-8b-instruct-fast", "rapido": True},
        ],
    },
    {
        "id": "huggingface",
        "nombre": "Hugging Face",
        "base": "https://router.huggingface.co/v1",
        "llave": "HF_TOKEN",
        "registro": "https://huggingface.co/settings/tokens",
        "prioridad": 5,
        "cuota_por_llave": True,
        "modelos": [
            {"id": "openai/gpt-oss-120b"},
            {"id": "deepseek-ai/DeepSeek-V3.1"},
            {"id": "Qwen/Qwen3-235B-A22B-Instruct-2507"},
            {"id": "meta-llama/Llama-3.3-70B-Instruct"},
        ],
    },
    {
        "id": "ollama",
        "nombre": "Ollama (local / CasaOS)",
        "base": "{OLLAMA_URL}",
        "base_defecto": {"OLLAMA_URL": "http://localhost:11434/v1"},
        "sin_llave": True,
        "cuerpo_extra": {"temperature": 0.2},  # el modelo pequeño acierta más las herramientas si improvisa poco
        "registro": "https://ollama.com/download",
        "prioridad": 7,
        "modelos": [],  # todos los modelos que tengas descargados
    },
    {
        "id": "pollinations",
        "nombre": "Pollinations (sin registro)",
        "chat_url": "https://text.pollinations.ai/openai",
        "base": "https://text.pollinations.ai",
        "sin_llave": True,
        "listar": False,
        "registro": "https://pollinations.ai",
        "prioridad": 9,
        "modelos": [{"id": "openai"}],
    },
]
