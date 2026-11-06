import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_FILE = OUTPUT_DIR / "cache.json"


class Settings:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    max_workers = int(os.getenv("MAX_WORKERS", "3"))
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", "").strip()
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "Business Development").strip()
    postal_info = os.getenv("SENDER_INFO", "Your company name, address, country").strip()
    send_delay_seconds = int(os.getenv("SEND_DELAY_SECONDS", "5"))
    imap_host = os.getenv("IMAP_HOST", "").strip()
    followup_days = int(os.getenv("FOLLOWUP_AFTER_DAYS", "5"))
    max_followups = int(os.getenv("MAX_FOLLOWUPS", "2"))
    app_password = os.getenv("APP_PASSWORD", "").strip()
    use_js_fallback = os.getenv("USE_JS_FALLBACK", "true").lower() == "true"
    user_agent = "Mozilla/5.0 (compatible; TradeLeadFinder/1.0; business research)"
    max_pages_per_site = 5
    request_timeout = 15


settings = Settings()
