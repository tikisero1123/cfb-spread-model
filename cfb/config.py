"""Config. Your CFBD key lives in the environment, never in the repo."""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CFBD_API_KEY = os.environ.get("CFBD_API_KEY", "")
CFBD_BASE_URL = "https://api.collegefootballdata.com"

# Project defaults
MIN_WEEK = 4          # Week 4+ only in v1 (early-season noise stays out)
SHRINK_K = 4.0        # shrinkage pseudo-count for point-in-time features


def require_key() -> str:
    if not CFBD_API_KEY:
        raise RuntimeError(
            "No CFBD_API_KEY found. Get a free key at "
            "https://collegefootballdata.com/key , then either:\n"
            "  export CFBD_API_KEY=your_key_here\n"
            "or put it in a .env file (see .env.example)."
        )
    return CFBD_API_KEY
