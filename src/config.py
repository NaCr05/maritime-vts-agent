from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]


def _get_ascii_path(path: Path) -> Path:
    """返回纯 ASCII 路径作为 HF 缓存目录，规避 Windows 中文路径问题。"""
    explicit_cache = os.environ.get("VTS_HF_CACHE_DIR", "")
    if explicit_cache:
        candidate = Path(explicit_cache).expanduser()
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass

    # 优先从环境变量获取已知的 ASCII 可写路径
    for var in ("USERPROFILE", "LOCALAPPDATA", "TEMP", "TMP"):
        val = os.environ.get(var, '')
        if val and all(ord(c) < 128 for c in val):
            candidate = Path(val) / "vts_hf_cache"
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except Exception:
                pass

    # 通用回退：不绑定任何本机用户名。极端情况下路径可能仍含非 ASCII，
    # 但不会把开发者机器路径写死到开源代码里。
    candidate = Path.home() / ".cache" / "maritime-vts-agent" / "hf"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


# 用纯 ASCII 路径作为 HF / sentence-transformers 缓存目录，
# 避免中文路径在 Windows 下出现 [Errno 22] 问题。
_CACHE_DIR = _get_ascii_path(BASE_DIR) / ".cache"
HF_HOME = os.environ["HF_HOME"] = str(_CACHE_DIR / "huggingface")
XDG_CACHE_HOME = os.environ["XDG_CACHE_HOME"] = str(_CACHE_DIR)
SENTENCE_TRANSFORMERS_HOME = os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(
    _CACHE_DIR / "sentence_transformers"
)
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DATA_DIR = BASE_DIR / "data"
AIS_KNOWLEDGE_DIR = DATA_DIR / "ais_knowledge"

load_dotenv(BASE_DIR / ".env")

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "paraphrase-multilingual-MiniLM-L12-v2"
)

# ---- 预定义禁航区 ----
# 可根据实际业务区域调整

RESTRICTED_ZONES = [
    {
        "name": "长江口核心区",
        "type": "rect",
        "lat_min": 30.80,
        "lat_max": 31.20,
        "lon_min": 121.80,
        "lon_max": 122.20,
        "description": "长江入海口核心管控水域",
    },
    {
        "name": "舟山港口",
        "type": "rect",
        "lat_min": 29.80,
        "lat_max": 30.30,
        "lon_min": 121.60,
        "lon_max": 122.30,
        "description": "浙江舟山群岛主要港口水域",
    },
    {
        "name": "军事演习区 A",
        "type": "circle",
        "lat": 30.50,
        "lon": 122.50,
        "radius_nm": 10.0,
        "description": "军事演习禁航区域（示例）",
    },
    {
        "name": "嵊泗渔场保护区",
        "type": "circle",
        "lat": 30.80,
        "lon": 122.30,
        "radius_nm": 8.0,
        "description": "重要渔业资源保护区（示例）",
    },
]
