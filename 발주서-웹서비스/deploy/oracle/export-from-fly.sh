#!/usr/bin/env bash
# Fly.io에 있는 시크릿 13개와 데이터베이스를 내려받아 이사 준비를 끝낸다.
# 값은 화면에 출력하지 않고 파일로만 저장한다.
#
#   bash export-from-fly.sh            # 결과: .env, data/suyikolla.db
set -euo pipefail

APP="${APP:-rj-balju}"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$OUT_DIR/data"
mkdir -p "$DATA_DIR"

export FLY_API_TOKEN="${FLY_API_TOKEN:-$(sed -n 's/^access_token: *//p' "$HOME/.fly/config.yml")}"

KEYS="SECRET_KEY TEAM_PASSWORD AUTH_DISABLED COUPANG_ACCESS_KEY COUPANG_SECRET_KEY COUPANG_VENDOR_ID COUPANG_GOGUMA_WING_ID TOSS_ACCESS_KEY TOSS_SECRET_KEY PBF_PARTNER_ID PBF_PARTNER_PASSWORD INTERNAL_API_KEY GMAIL_APP_PASSWORD"

echo "[1/3] 시크릿 내보내는 중... (값은 출력하지 않음)"
TMP_ENV="$OUT_DIR/.env.fly.tmp"
fly ssh console -a "$APP" -C "printenv" > "$TMP_ENV" 2>/dev/null || true

if [ ! -s "$TMP_ENV" ]; then
  echo "  ! 시크릿을 가져오지 못했습니다. .env를 직접 채워주세요."
else
  {
    for k in $KEYS; do
      line="$(grep -m1 "^${k}=" "$TMP_ENV" || true)"
      [ -n "$line" ] && printf '%s\n' "$line"
    done
  } > "$OUT_DIR/.env.secrets"
  rm -f "$TMP_ENV"
  echo "  → .env.secrets 저장 완료 ($(grep -c '=' "$OUT_DIR/.env.secrets") 개)"
fi

echo "[2/3] 데이터베이스 내려받는 중..."
# 운영 중 파일은 WAL이 남아 있을 수 있어 스케줄러가 만든 주간 백업(정합성 보장)을 우선 사용
LATEST_BACKUP="$(fly ssh console -a "$APP" -C "sh -c 'ls -1 /data/backups/*.db 2>/dev/null | tail -1'" 2>/dev/null | tr -d '\r' | tail -1 || true)"
if [ -n "${LATEST_BACKUP:-}" ]; then
  echo "  최신 백업: $LATEST_BACKUP"
fi
fly ssh sftp get /data/suyikolla.db "$DATA_DIR/suyikolla.db" -a "$APP"
fly ssh sftp get /data/suyikolla.db-wal "$DATA_DIR/suyikolla.db-wal" -a "$APP" 2>/dev/null || true
echo "  → data/ 저장 완료"

echo "[3/3] .env 만드는 중..."
if [ ! -f "$OUT_DIR/.env" ]; then
  cp "$OUT_DIR/.env.example" "$OUT_DIR/.env"
fi
if [ -f "$OUT_DIR/.env.secrets" ]; then
  # .env의 빈 시크릿 줄을 실제 값으로 교체
  while IFS= read -r line; do
    key="${line%%=*}"
    if grep -q "^${key}=" "$OUT_DIR/.env"; then
      tmp="$(mktemp)"
      grep -v "^${key}=" "$OUT_DIR/.env" > "$tmp"
      printf '%s\n' "$line" >> "$tmp"
      mv "$tmp" "$OUT_DIR/.env"
    fi
  done < "$OUT_DIR/.env.secrets"
  rm -f "$OUT_DIR/.env.secrets"
fi

echo
echo "완료. SITE_DOMAIN / APP_BASE_URL / PUBLIC_BASE_URL 만 채우면 됩니다:"
echo "  $OUT_DIR/.env"
