"""SQLite → Supabase(Postgres) 무손실 이전 스크립트.

사용법:
    python scripts/migrate_sqlite_to_supabase.py \
        --sqlite-path /path/to/app.db \
        --pg-dsn "postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres"

옵션:
    --dry-run       실제 삽입 없이 읽기만 수행
    --truncate      삽입 전 대상 테이블 비우기(재실행 시 사용)
    --verify-only   이전 없이 행수/합계 검증만 수행
"""

import argparse
import asyncio
import os
import sqlite3
import sys
from typing import Any

import asyncpg


# ────────────────────────────────────────────────────────────
# 삽입 순서 (FK 의존 관계 준수)
# IDENTITY PK 를 가지는 테이블은 reset_sequences 에도 포함됨
# ────────────────────────────────────────────────────────────

# (table_name, has_identity_pk)
TABLE_ORDER: list[tuple[str, bool]] = [
    # 전역/운영 — PK 가 외부 키여서 IDENTITY 아님
    ("cached_products",               False),  # PK = seller_product_id (외부)
    ("cached_orders",                 False),  # PK = order_id (TEXT 외부)
    # IDENTITY PK 전역 테이블
    ("daily_sales",                   True),
    ("pricing_rules",                 True),
    ("pricing_log",                   True),
    ("app_settings",                  False),  # PK = TEXT key
    ("plans",                         True),
    ("supplier_price_snapshots",      True),
    ("supplier_price_monitor_runs",   True),
    ("risk_snapshots",                True),
    # 사용자 계층 (부모→자식 순)
    ("users",                         True),
    ("user_templates",                True),
    ("user_products",                 True),
    ("user_product_options",          True),
    ("blocked_ips",                   True),
    ("subscriptions",                 True),
    ("order_batches",                 True),
    ("order_batch_items",             True),
    # 사용자 종속 로그성 테이블
    ("billing_events",                True),
    ("usage_logs",                    True),
    ("option_sales",                  True),
    ("daily_settlement_snapshots",    True),
]

# TRUNCATE 시 역순(자식→부모)으로 비운다
TRUNCATE_ORDER = list(reversed([t for t, _ in TABLE_ORDER]))

# ────────────────────────────────────────────────────────────
# 테이블별 컬럼 정의 (schema.sql / db.py 에서 추출한 확정 매핑)
# 컬럼 순서는 SQLite SELECT * 와 동일해야 함 — 명시 삽입이므로 무관
# ────────────────────────────────────────────────────────────

TABLE_COLUMNS: dict[str, list[str]] = {
    "cached_products": [
        "seller_product_id", "product_name", "sale_price", "stock",
        "status", "vendor_item_id", "category", "data_json", "updated_at",
    ],
    "cached_orders": [
        "order_id", "ordered_at", "product_name", "seller_product_id",
        "quantity", "sale_price", "status", "receiver_name", "data_json", "cached_at",
    ],
    "daily_sales": [
        "id", "product_id", "product_name", "date", "total_quantity", "total_revenue",
    ],
    "pricing_rules": [
        "id", "product_id", "product_name", "min_margin_pct",
        "min_price", "max_price", "ad_stop_threshold", "active", "created_at",
    ],
    "pricing_log": [
        "id", "product_id", "product_name", "old_price", "new_price",
        "margin_before", "margin_after", "reason", "executed_at",
    ],
    "app_settings": ["key", "value", "updated_at"],
    "plans": [
        "id", "code", "name", "price_krw", "max_products",
        "max_monthly_orders", "features_json", "active",
    ],
    "supplier_price_snapshots": [
        "id", "monitor_key", "supplier_name", "product_name", "option_name",
        "supplier_option_name", "normalized_option_key", "supplier_price", "checked_at",
    ],
    "supplier_price_monitor_runs": [
        "id", "run_date", "monitor_key", "supplier_name", "product_name",
        "status", "total_items", "changed_items", "blue_count", "red_count",
        "same_count", "output_filename", "error_message", "checked_at",
    ],
    "risk_snapshots": [
        "id", "product_id", "product_name", "score", "level",
        "stock", "avg_daily_sales", "days_remaining", "margin_pct", "snapshot_at",
    ],
    "users": [
        "id", "username", "password_hash", "email", "google_id", "kakao_id",
        "display_name", "avatar_url", "role", "is_active", "created_at", "updated_at",
        # auth_user_id 는 Supabase Phase 3 에서 채움 — SQLite 에 없으므로 NULL 삽입
    ],
    "blocked_ips": [
        "id", "ip_address", "user_id", "blocked_by", "reason", "created_at",
    ],
    "user_templates": [
        "id", "user_id", "template_name", "file_data", "uploaded_at",
    ],
    "user_products": [
        "id", "user_id", "product_label", "coupang_product_keyword",
        "template_id", "output_filename_pattern", "is_active", "created_at",
    ],
    "user_product_options": [
        "id", "user_product_id", "coupang_option_keyword", "vendor_option_name",
        "template_target_cell", "unit_price_krw", "created_at",
    ],
    "subscriptions": [
        "id", "user_id", "plan_code", "status", "billing_key", "customer_key",
        "current_period_start", "current_period_end", "cancel_at_period_end",
        "created_at", "updated_at",
    ],
    "billing_events": [
        "id", "user_id", "type", "amount_krw", "toss_payment_key",
        "toss_order_id", "raw_json", "created_at",
    ],
    "usage_logs": [
        "id", "user_id", "event_type", "product_label",
        "order_count", "ym", "created_at",
    ],
    "option_sales": [
        "id", "user_id", "product_label", "coupang_option_keyword",
        "vendor_option_name", "quantity", "external_order_id", "ymd", "ym", "created_at",
    ],
    "daily_settlement_snapshots": [
        "id", "user_id", "product_label", "coupang_option_keyword",
        "vendor_option_name", "quantity", "unit_price_krw", "unit_price_source",
        "supplier_price_option_name", "settlement_krw", "ymd", "ym",
        "logic_version", "snapshot_at",
    ],
    "order_batches": [
        "id", "user_id", "source_key", "batch_name", "template_name",
        "output_filename", "total_rows", "total_quantity", "metadata_json",
        "processed_at", "sync_status", "sync_error",
    ],
    "order_batch_items": [
        "id", "batch_id", "product_name", "platform_option_name", "supply_option_name",
        "quantity", "external_order_id", "receiver_name", "receiver_phone",
        "receiver_address", "memo", "created_at",
    ],
}

# SQLite 에서 SELECT 시 컬럼명 (users 는 auth_user_id 가 없으므로 별도 처리)
SQLITE_COLUMNS: dict[str, list[str]] = {
    tbl: cols for tbl, cols in TABLE_COLUMNS.items()
}
# users 테이블: SQLite 에 auth_user_id 없음 → SELECT 컬럼에서 제외
SQLITE_COLUMNS["users"] = [c for c in TABLE_COLUMNS["users"] if c != "auth_user_id"]

# Postgres INSERT 시 컬럼명 (users: auth_user_id=NULL 명시)
PG_COLUMNS: dict[str, list[str]] = dict(TABLE_COLUMNS)  # 그대로 — users 도 포함
# users 테이블도 auth_user_id 제외하고 삽입 (NULL default 허용)
PG_COLUMNS["users"] = SQLITE_COLUMNS["users"]

# BLOB 컬럼 (SQLite bytes → Postgres BYTEA)
BLOB_COLUMNS: dict[str, set[str]] = {
    "user_templates": {"file_data"},
}

# 합계 검증 대상: (table, column)
SUM_CHECK_COLUMNS: list[tuple[str, str]] = [
    ("option_sales",                 "quantity"),
    ("daily_settlement_snapshots",   "settlement_krw"),
    ("billing_events",               "amount_krw"),
    ("daily_sales",                  "total_revenue"),
    ("user_product_options",         "unit_price_krw"),
]

BATCH_SIZE = 500


# ────────────────────────────────────────────────────────────
# 헬퍼
# ────────────────────────────────────────────────────────────

def _sqlite_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def _check_sqlite_columns(conn: sqlite3.Connection, table: str, wanted: list[str]) -> list[str]:
    """SQLite 테이블에 실제 존재하는 컬럼만 반환 (ALTER TABLE 마이그레이션 미적용 DB 대응)."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    available = [c for c in wanted if c in existing]
    missing = [c for c in wanted if c not in existing]
    if missing:
        print(f"  [WARN] {table}: SQLite 에 없는 컬럼 무시 → {missing}")
    return available


def _pg_placeholders(cols: list[str]) -> str:
    return ", ".join(f"${i+1}" for i in range(len(cols)))


def _pg_insert_sql(table: str, cols: list[str], on_conflict: str = "DO NOTHING") -> str:
    col_str = ", ".join(cols)
    placeholder_str = _pg_placeholders(cols)
    return f"INSERT INTO {table} ({col_str}) VALUES ({placeholder_str}) ON CONFLICT {on_conflict}"


def _coerce_row(row: sqlite3.Row, sqlite_cols: list[str], pg_cols: list[str],
                blob_cols: set[str]) -> tuple[Any, ...]:
    """SQLite Row → asyncpg tuple 변환. BLOB → bytes, 나머지는 그대로."""
    result = []
    row_dict = dict(row)
    for col in pg_cols:
        if col not in row_dict:
            # SQLite 에 없는 컬럼(마이그레이션 컬럼) — 기본값(0 또는 '')으로 채움
            result.append(None)
        elif col in blob_cols:
            val = row_dict[col]
            result.append(bytes(val) if val is not None else None)
        else:
            result.append(row_dict[col])
    return tuple(result)


async def _reset_sequence(pg: asyncpg.Connection, table: str) -> None:
    """IDENTITY 시퀀스를 현재 MAX(id) 로 재설정."""
    await pg.execute(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
        f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM {table}), 1))"
    )


# ────────────────────────────────────────────────────────────
# 메인 이전 로직
# ────────────────────────────────────────────────────────────

async def truncate_tables(pg: asyncpg.Connection, dry_run: bool) -> None:
    print("\n[TRUNCATE] 대상 테이블 비우는 중 (자식→부모 순)...")
    if dry_run:
        print("  dry-run: TRUNCATE 건너뜀")
        return
    # CASCADE 로 FK 자식도 함께 비움 — 순서대로 해도 되지만 CASCADE 로 안전하게
    for table in TRUNCATE_ORDER:
        await pg.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
        print(f"  TRUNCATED {table}")


async def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg: asyncpg.Connection,
    table: str,
    has_identity: bool,
    dry_run: bool,
) -> tuple[int, int]:
    """단일 테이블 이전. (sqlite_rows, pg_inserted) 반환."""
    sqlite_cols_wanted = SQLITE_COLUMNS.get(table, [])
    sqlite_cols = _check_sqlite_columns(sqlite_conn, table, sqlite_cols_wanted)
    pg_cols = [c for c in PG_COLUMNS.get(table, []) if c in sqlite_cols]

    if not sqlite_cols:
        print(f"  [SKIP] {table}: 컬럼 없음")
        return 0, 0

    # SQLite 전체 읽기
    cur = sqlite_conn.execute(
        f"SELECT {', '.join(sqlite_cols)} FROM {table}"
    )
    rows = cur.fetchall()
    sqlite_count = len(rows)

    if sqlite_count == 0:
        print(f"  {table}: 0 행 (건너뜀)")
        return 0, 0

    blob_cols = BLOB_COLUMNS.get(table, set())
    sql = _pg_insert_sql(table, pg_cols)

    inserted = 0
    if not dry_run:
        for batch_start in range(0, sqlite_count, BATCH_SIZE):
            batch = rows[batch_start: batch_start + BATCH_SIZE]
            records = [_coerce_row(r, sqlite_cols, pg_cols, blob_cols) for r in batch]
            await pg.executemany(sql, records)
            inserted += len(records)
    else:
        inserted = sqlite_count  # dry-run 은 읽기만

    print(f"  {table}: sqlite={sqlite_count} → pg_inserted={inserted}")
    return sqlite_count, inserted


async def migrate(sqlite_path: str, pg_dsn: str, dry_run: bool, truncate: bool) -> None:
    print(f"\n[MIGRATE] SQLite: {sqlite_path}")
    print(f"          Postgres: (DSN 마스킹)")
    print(f"          dry_run={dry_run}, truncate={truncate}\n")

    sqlite_conn = _sqlite_connect(sqlite_path)

    pg: asyncpg.Connection = await asyncpg.connect(pg_dsn)

    try:
        if truncate:
            await truncate_tables(pg, dry_run)

        total_sqlite = 0
        total_pg = 0

        for table, has_identity in TABLE_ORDER:
            s, p = await migrate_table(sqlite_conn, pg, table, has_identity, dry_run)
            total_sqlite += s
            total_pg += p

            # 시퀀스 재설정 (IDENTITY 테이블, 삽입 후)
            if has_identity and not dry_run and p > 0:
                await _reset_sequence(pg, table)

        print(f"\n[DONE] 총 sqlite={total_sqlite} 행, pg_inserted={total_pg} 행")
        if dry_run:
            print("       (dry-run: Postgres 에 실제로 쓰지 않음)")

    finally:
        sqlite_conn.close()
        await pg.close()


# ────────────────────────────────────────────────────────────
# 검증 로직
# ────────────────────────────────────────────────────────────

async def verify(sqlite_path: str, pg_dsn: str) -> bool:
    print(f"\n[VERIFY] SQLite: {sqlite_path}")
    print(f"         Postgres: (DSN 마스킹)\n")

    sqlite_conn = _sqlite_connect(sqlite_path)
    pg: asyncpg.Connection = await asyncpg.connect(pg_dsn)

    all_ok = True
    rows_report: list[tuple[str, int, int, str]] = []

    try:
        # 1. 행수 대조
        print("── 행수 대조 ─────────────────────────────────")
        for table, _ in TABLE_ORDER:
            cur = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}")
            sqlite_cnt = cur.fetchone()[0]

            pg_cnt: int = await pg.fetchval(f"SELECT COUNT(*) FROM {table}")

            ok = sqlite_cnt == pg_cnt
            status = "OK" if ok else "MISMATCH"
            rows_report.append((table, sqlite_cnt, pg_cnt, status))
            if not ok:
                all_ok = False

        # 표 출력
        col_w = max(len(t) for t, _ in TABLE_ORDER) + 2
        print(f"{'테이블':<{col_w}} {'SQLite':>10} {'Postgres':>10} {'결과':>10}")
        print("-" * (col_w + 34))
        for table, sc, pc, st in rows_report:
            marker = "" if st == "OK" else " <-- ERROR"
            print(f"{table:<{col_w}} {sc:>10} {pc:>10} {st:>10}{marker}")

        # 2. 핵심 합계 대조
        print("\n── 합계 대조 ─────────────────────────────────")
        print(f"{'테이블.컬럼':<50} {'SQLite 합계':>15} {'Postgres 합계':>15} {'결과':>8}")
        print("-" * 92)
        for table, col in SUM_CHECK_COLUMNS:
            try:
                cur = sqlite_conn.execute(f"SELECT COALESCE(SUM({col}), 0) FROM {table}")
                sqlite_sum = cur.fetchone()[0] or 0

                pg_sum = await pg.fetchval(
                    f"SELECT COALESCE(SUM({col}), 0) FROM {table}"
                )
                pg_sum = pg_sum or 0

                ok = int(sqlite_sum) == int(pg_sum)
                st = "OK" if ok else "MISMATCH"
                if not ok:
                    all_ok = False
                marker = "" if ok else " <-- ERROR"
                label = f"{table}.{col}"
                print(f"{label:<50} {int(sqlite_sum):>15} {int(pg_sum):>15} {st:>8}{marker}")
            except Exception as e:
                print(f"  [WARN] {table}.{col} 합계 검증 실패: {e}")

        # 3. PK 샘플 대조 (처음 10개 id)
        print("\n── PK 샘플 대조 (id 앞 10개) ─────────────────")
        sample_tables = [
            "users", "order_batches", "plans", "subscriptions",
            "billing_events", "option_sales",
        ]
        for table in sample_tables:
            try:
                cur = sqlite_conn.execute(f"SELECT id FROM {table} ORDER BY id LIMIT 10")
                sqlite_ids = [r[0] for r in cur.fetchall()]
                if not sqlite_ids:
                    print(f"  {table}: 데이터 없음 (건너뜀)")
                    continue

                pg_ids_rows = await pg.fetch(
                    f"SELECT id FROM {table} WHERE id = ANY($1::bigint[]) ORDER BY id",
                    sqlite_ids,
                )
                pg_ids = [r["id"] for r in pg_ids_rows]

                missing = set(sqlite_ids) - set(pg_ids)
                if missing:
                    all_ok = False
                    print(f"  {table}: MISSING ids = {sorted(missing)[:5]}  <-- ERROR")
                else:
                    print(f"  {table}: {len(sqlite_ids)} 개 PK 확인 OK")
            except Exception as e:
                print(f"  [WARN] {table} PK 샘플 검증 실패: {e}")

    finally:
        sqlite_conn.close()
        await pg.close()

    print("\n" + ("=" * 50))
    if all_ok:
        print("검증 결과: 전체 OK")
    else:
        print("검증 결과: 불일치 항목 있음 (위 ERROR 확인)")
    print("=" * 50)

    return all_ok


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SQLite → Supabase(Postgres) 데이터 이전 스크립트"
    )
    parser.add_argument(
        "--sqlite-path",
        default=os.environ.get("DATABASE_PATH", "app.db"),
        help="SQLite 파일 경로 (기본: DATABASE_PATH 환경변수 또는 app.db)",
    )
    parser.add_argument(
        "--pg-dsn",
        default=os.environ.get("SUPABASE_DB_URL", ""),
        help="Postgres DSN (기본: SUPABASE_DB_URL 환경변수)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="SQLite 읽기만 하고 Postgres 에 쓰지 않음",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="삽입 전 대상 테이블을 비움 (재실행 시 사용, RESTART IDENTITY CASCADE)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="이전 없이 행수/합계 검증만 수행",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.sqlite_path:
        print("ERROR: --sqlite-path 또는 DATABASE_PATH 환경변수가 필요합니다.")
        sys.exit(1)

    if not args.pg_dsn:
        print("ERROR: --pg-dsn 또는 SUPABASE_DB_URL 환경변수가 필요합니다.")
        sys.exit(1)

    if args.verify_only:
        ok = asyncio.run(verify(args.sqlite_path, args.pg_dsn))
        sys.exit(0 if ok else 1)
    else:
        asyncio.run(
            migrate(
                sqlite_path=args.sqlite_path,
                pg_dsn=args.pg_dsn,
                dry_run=args.dry_run,
                truncate=args.truncate,
            )
        )
        if not args.dry_run:
            print("\n[자동 검증] 이전 완료 후 행수 대조 실행 중...")
            ok = asyncio.run(verify(args.sqlite_path, args.pg_dsn))
            sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
