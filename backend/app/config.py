import os

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

TICK_SECONDS = int(os.environ.get("TICK_SECONDS", "300"))
DIARY_THRESHOLD_HOURS = float(os.environ.get("DIARY_THRESHOLD_HOURS", "6"))
