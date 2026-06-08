import os
from pathlib import Path

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-2024")
TEAM_PASSWORD = os.getenv("TEAM_PASSWORD", "rjsystems2024")
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/uploads"))
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7 days

# Coupang Open API
COUPANG_VENDOR_ID = os.getenv("COUPANG_VENDOR_ID", "")
COUPANG_ACCESS_KEY = os.getenv("COUPANG_ACCESS_KEY", "")
COUPANG_SECRET_KEY = os.getenv("COUPANG_SECRET_KEY", "")

# Toss Shopping API
TOSS_ACCESS_KEY = os.getenv("TOSS_ACCESS_KEY", "")
TOSS_SECRET_KEY = os.getenv("TOSS_SECRET_KEY", "")

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/suyikolla.db")

# Deployment mode: 'saas' (hosted, multi-tenant, billing enabled) or 'onprem' (self-hosted, no billing)
DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "saas").lower()
DISABLE_SIGNUP = os.getenv("DISABLE_SIGNUP", "false").lower() == "true"
DISABLE_BILLING = os.getenv("DISABLE_BILLING", "false").lower() == "true" or DEPLOYMENT_MODE == "onprem"
DISABLE_QUOTA = os.getenv("DISABLE_QUOTA", "false").lower() == "true" or DEPLOYMENT_MODE == "onprem"
LICENSE_KEY = os.getenv("LICENSE_KEY", "")

# Toss Payments (subscription billing)
TOSS_PAY_SECRET_KEY = os.getenv("TOSS_PAY_SECRET_KEY", "")
TOSS_PAY_CLIENT_KEY = os.getenv("TOSS_PAY_CLIENT_KEY", "")
TOSS_PAY_API_BASE = os.getenv("TOSS_PAY_API_BASE", "https://api.tosspayments.com")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5173")

# Subscription pricing (KRW / month)
PRO_PLAN_PRICE = int(os.getenv("PRO_PLAN_PRICE", "29000"))

# OAuth (Social Login)
KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID", "")          # Kakao JS Key
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")         # Google OAuth Client ID

# Optional Supabase mirror for order automation analytics
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_SCHEMA = os.getenv("SUPABASE_SCHEMA", "public")
SUPABASE_BATCHES_TABLE = os.getenv("SUPABASE_BATCHES_TABLE", "automation_batches")
SUPABASE_BATCH_ITEMS_TABLE = os.getenv("SUPABASE_BATCH_ITEMS_TABLE", "automation_batch_items")

# AdminPlus supplier sourcing monitor
PBF_PARTNER_ID = os.getenv("PBF_PARTNER_ID", "")
PBF_PARTNER_PASSWORD = os.getenv("PBF_PARTNER_PASSWORD", "")

# Internal bridge used when a deployment's outbound IP is not allowlisted by
# marketplace APIs. Keep this empty except on apps that should proxy requests.
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
GOGUMA_API_PROXY_BASE_URL = os.getenv("GOGUMA_API_PROXY_BASE_URL", "").rstrip("/")
