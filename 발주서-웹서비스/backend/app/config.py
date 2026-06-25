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
# 기본 COUPANG_* 값은 기존/공용 계정 호환용으로 유지한다.
COUPANG_VENDOR_ID = os.getenv("COUPANG_VENDOR_ID", "")
COUPANG_ACCESS_KEY = os.getenv("COUPANG_ACCESS_KEY", "")
COUPANG_SECRET_KEY = os.getenv("COUPANG_SECRET_KEY", "")

# 고구마는 별도 쿠팡 계정으로 운영한다. 없으면 기존 COUPANG_*으로 fallback.
COUPANG_GOGUMA_VENDOR_ID = os.getenv("COUPANG_GOGUMA_VENDOR_ID") or COUPANG_VENDOR_ID
COUPANG_GOGUMA_ACCESS_KEY = os.getenv("COUPANG_GOGUMA_ACCESS_KEY") or COUPANG_ACCESS_KEY
COUPANG_GOGUMA_SECRET_KEY = os.getenv("COUPANG_GOGUMA_SECRET_KEY") or COUPANG_SECRET_KEY

# 과일/농수산물 공용 쿠팡 계정. 없으면 기존 COUPANG_*으로 fallback.
COUPANG_PRODUCE_VENDOR_ID = os.getenv("COUPANG_PRODUCE_VENDOR_ID") or COUPANG_VENDOR_ID
COUPANG_PRODUCE_ACCESS_KEY = os.getenv("COUPANG_PRODUCE_ACCESS_KEY") or COUPANG_ACCESS_KEY
COUPANG_PRODUCE_SECRET_KEY = os.getenv("COUPANG_PRODUCE_SECRET_KEY") or COUPANG_SECRET_KEY

# Toss Shopping API
# 새 로컬 자동화는 TOSS_CLIENT_ID/SECRET을 쓰고, 기존 웹서비스는 TOSS_ACCESS/SECRET을 썼다.
# 둘 다 지원해서 배포 시크릿 이름 차이로 주문 조회가 깨지지 않게 한다.
TOSS_ACCESS_KEY = os.getenv("TOSS_ACCESS_KEY") or os.getenv("TOSS_CLIENT_ID", "")
TOSS_SECRET_KEY = os.getenv("TOSS_SECRET_KEY") or os.getenv("TOSS_CLIENT_SECRET", "")
TOSS_API_BASE_URL = os.getenv("TOSS_API_BASE_URL", "https://shopping-fep.toss.im").rstrip("/")
TOSS_OAUTH_TOKEN_URL = os.getenv("TOSS_OAUTH_TOKEN_URL", "https://oauth2.cert.toss.im/token")
TOSS_OAUTH_SCOPE = os.getenv("TOSS_OAUTH_SCOPE", "toss-shopping-fep:read toss-shopping-fep:write")

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
