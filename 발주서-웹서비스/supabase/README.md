# 발주서 SaaS — Supabase Phase 0 적용 가이드

## 개요

SQLite(로컬 개발) → Supabase Postgres(운영)으로 데이터를 무손실 이전하는 절차입니다.  
실행 순서: schema.sql → rls_policies.sql → seed.sql → migrate 스크립트 → 검증.

---

## 1. Supabase 프로젝트 생성

1. [supabase.com/dashboard](https://supabase.com/dashboard) 에서 **New project** 클릭.
2. 프로젝트 이름, 조직, 리전(Northeast Asia - Tokyo 권장) 입력.
3. **Database Password** 를 안전하게 설정하고 별도 보관.
4. 프로젝트 생성 완료 후 **Project Settings → Database** 탭으로 이동.
5. **Connection string** 섹션에서 두 가지 DSN 복사:
   - **Session pooler** (포트 5432, 앱 서버용): `postgresql://postgres.xxx:PASSWORD@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres`
   - **Direct connection** (포트 5432, 마이그레이션 스크립트용): `postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres`
6. **Project Settings → API** 탭에서 아래 키 복사:
   - `URL` → `SUPABASE_URL`
   - `anon` public key → `SUPABASE_ANON_KEY`
   - `service_role` secret key → `SUPABASE_SERVICE_ROLE_KEY`

---

## 2. 필요한 환경변수

`.env` 또는 배포 환경에 아래 변수를 설정합니다.

```
# Postgres DSN (Direct connection — 마이그레이션 및 백엔드 직접 연결용)
SUPABASE_DB_URL=postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres

# Supabase REST/Auth API
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...   # 절대 클라이언트에 노출 금지

# 기존 SQLite 경로 (이전 시에만 필요)
DATABASE_PATH=/path/to/app.db
```

---

## 3. 스키마·정책·시드 적용

Supabase 대시보드 **SQL Editor** 또는 `psql` 로 아래 순서대로 실행합니다.

### 방법 A — SQL Editor (GUI)

1. SQL Editor → **New query**
2. `supabase/schema.sql` 내용 붙여넣기 → **Run**
3. `supabase/rls_policies.sql` 내용 붙여넣기 → **Run**
4. `supabase/seed.sql` 내용 붙여넣기 → **Run**

### 방법 B — psql (CLI)

```bash
PGPASSWORD=PASSWORD psql \
  "postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres" \
  -f supabase/schema.sql \
  -f supabase/rls_policies.sql \
  -f supabase/seed.sql
```

---

## 4. 마이그레이션 스크립트 실행

### 사전 준비

```bash
pip install asyncpg==0.29.0
```

### 이전 실행

```bash
# 기본 실행 (SQLite → Postgres 이전 후 자동 검증)
python scripts/migrate_sqlite_to_supabase.py \
  --sqlite-path /path/to/app.db \
  --pg-dsn "postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres"

# 재실행 시 (기존 데이터 삭제 후 재삽입)
python scripts/migrate_sqlite_to_supabase.py \
  --sqlite-path /path/to/app.db \
  --pg-dsn "..." \
  --truncate

# 실제 쓰기 없이 읽기 테스트
python scripts/migrate_sqlite_to_supabase.py \
  --sqlite-path /path/to/app.db \
  --pg-dsn "..." \
  --dry-run
```

환경변수로 지정하는 경우:

```bash
export DATABASE_PATH=/path/to/app.db
export SUPABASE_DB_URL="postgresql://..."
python scripts/migrate_sqlite_to_supabase.py
```

---

## 5. 검증

이전 완료 후 스크립트가 자동으로 검증을 수행합니다.  
별도로 검증만 실행하려면:

```bash
python scripts/migrate_sqlite_to_supabase.py \
  --sqlite-path /path/to/app.db \
  --pg-dsn "..." \
  --verify-only
```

검증 항목:

| 항목 | 내용 |
|------|------|
| 행수 대조 | 22개 테이블 전체 COUNT 일치 확인 |
| 합계 대조 | option_sales.quantity, settlement_krw, amount_krw, total_revenue, unit_price_krw |
| PK 샘플 | users/order_batches/plans 등 앞 10개 id 존재 확인 |

---

## 6. 롤백 방법

스키마 전체를 삭제하려면 SQL Editor 에서 실행:

```sql
-- 주의: 모든 데이터가 삭제됩니다
DROP TABLE IF EXISTS
  daily_settlement_snapshots, option_sales, usage_logs, billing_events,
  order_batch_items, order_batches, subscriptions, blocked_ips,
  user_product_options, user_products, user_templates, users,
  risk_snapshots, supplier_price_monitor_runs, supplier_price_snapshots,
  plans, app_settings, pricing_log, pricing_rules, daily_sales,
  cached_orders, cached_products
CASCADE;
```

---

## 7. 주의사항

- **`SUPABASE_SERVICE_ROLE_KEY`** 는 RLS 를 우회하는 관리자 키입니다. 서버 환경변수에만 보관하고 절대 클라이언트(브라우저/앱)에 노출하지 마십시오.
- 마이그레이션 스크립트는 **Direct connection** DSN(포트 5432) 을 사용해야 합니다. Session pooler(포트 6543)는 `COPY` 명령 및 세션 레벨 설정과 호환되지 않을 수 있습니다.
- `--truncate` 플래그는 `RESTART IDENTITY CASCADE` 로 자식 테이블을 포함해 전체 삭제합니다. 운영 환경에서 사용 시 데이터가 완전히 삭제되므로 주의하십시오.
- Supabase 무료 플랜은 1주일 비활성 시 프로젝트가 일시 중지됩니다. Pro 플랜 전환 또는 정기 접속으로 유지 필요.

---

## 8. 다음 단계

| Phase | 내용 |
|-------|------|
| Phase 1 | FastAPI 백엔드를 SQLite → asyncpg(Supabase Postgres)로 교체. `DATABASE_URL` 환경변수 전환. |
| Phase 2 | Supabase Storage 연동(엑셀 템플릿 파일 BYTEA → Storage 버킷 이전). RLS 정책 튜닝. |
| Phase 3 | Supabase Auth 연동. `users.auth_user_id` 컬럼 채움. 소셜 로그인(카카오/구글) OAuth 리디렉션 Supabase 처리. |
