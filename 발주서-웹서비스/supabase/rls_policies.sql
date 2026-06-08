-- ============================================================
--  발주서 자동화 SaaS — RLS (Row Level Security) 정책 (Phase 0)
--  전략:
--   - FastAPI 백엔드는 service_role 키로 접속 -> RLS 자동 우회 (기존 앱레벨 격리 유지)
--   - RLS는 "심층 방어 + 미래 프론트 직접접속(anon/authenticated) 대비"로 활성화
--   - authenticated 롤은 자신의 데이터만 (auth.uid() -> users.id 매핑)
--   - 운영/전역 테이블은 정책 미부여 = service_role 전용 (plans만 읽기 허용)
--  실행: schema.sql 이후
-- ============================================================

-- auth.uid()(Supabase Auth UUID) -> 내부 users.id(BIGINT) 매핑 헬퍼
CREATE OR REPLACE FUNCTION public.current_app_user_id()
RETURNS BIGINT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id FROM public.users WHERE auth_user_id = auth.uid()
$$;

-- ---------- 1) 사용자 본인(users) ----------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_self ON users
    FOR ALL TO authenticated
    USING (auth_user_id = auth.uid())
    WITH CHECK (auth_user_id = auth.uid());

-- ---------- 2) user_id 직접 보유 테이블 (테넌트 격리) ----------
-- user_templates
ALTER TABLE user_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON user_templates
    FOR ALL TO authenticated
    USING (user_id = public.current_app_user_id())
    WITH CHECK (user_id = public.current_app_user_id());

-- user_products
ALTER TABLE user_products ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON user_products
    FOR ALL TO authenticated
    USING (user_id = public.current_app_user_id())
    WITH CHECK (user_id = public.current_app_user_id());

-- subscriptions (구독: 본인 읽기/수정은 백엔드 경유 권장이나 RLS도 격리)
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON subscriptions
    FOR ALL TO authenticated
    USING (user_id = public.current_app_user_id())
    WITH CHECK (user_id = public.current_app_user_id());

-- billing_events (결제 이력: 본인 읽기만, 쓰기는 service_role)
ALTER TABLE billing_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON billing_events
    FOR SELECT TO authenticated
    USING (user_id = public.current_app_user_id());

-- usage_logs (본인 읽기만)
ALTER TABLE usage_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON usage_logs
    FOR SELECT TO authenticated
    USING (user_id = public.current_app_user_id());

-- option_sales
ALTER TABLE option_sales ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON option_sales
    FOR ALL TO authenticated
    USING (user_id = public.current_app_user_id())
    WITH CHECK (user_id = public.current_app_user_id());

-- daily_settlement_snapshots
ALTER TABLE daily_settlement_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON daily_settlement_snapshots
    FOR ALL TO authenticated
    USING (user_id = public.current_app_user_id())
    WITH CHECK (user_id = public.current_app_user_id());

-- order_batches
ALTER TABLE order_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON order_batches
    FOR ALL TO authenticated
    USING (user_id = public.current_app_user_id())
    WITH CHECK (user_id = public.current_app_user_id());

-- ---------- 3) 간접 소유 테이블 (부모 경유 격리) ----------
-- user_product_options -> user_products
ALTER TABLE user_product_options ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON user_product_options
    FOR ALL TO authenticated
    USING (
        user_product_id IN (
            SELECT id FROM user_products WHERE user_id = public.current_app_user_id()
        )
    )
    WITH CHECK (
        user_product_id IN (
            SELECT id FROM user_products WHERE user_id = public.current_app_user_id()
        )
    );

-- order_batch_items -> order_batches
ALTER TABLE order_batch_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON order_batch_items
    FOR ALL TO authenticated
    USING (
        batch_id IN (
            SELECT id FROM order_batches WHERE user_id = public.current_app_user_id()
        )
    )
    WITH CHECK (
        batch_id IN (
            SELECT id FROM order_batches WHERE user_id = public.current_app_user_id()
        )
    );

-- ---------- 4) 전역/운영 테이블 ----------
-- plans: 인증 사용자 읽기 허용(가격표 표시), 수정은 service_role 전용
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
CREATE POLICY plans_read ON plans
    FOR SELECT TO authenticated
    USING (active = 1);

-- 나머지 운영 테이블: RLS 활성화 + 정책 미부여 = service_role 전용 접근
--  (cached_products / cached_orders / daily_sales / pricing_rules / pricing_log /
--   app_settings / supplier_price_snapshots / supplier_price_monitor_runs /
--   risk_snapshots / blocked_ips)
ALTER TABLE cached_products              ENABLE ROW LEVEL SECURITY;
ALTER TABLE cached_orders                ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_sales                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE pricing_rules                ENABLE ROW LEVEL SECURITY;
ALTER TABLE pricing_log                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_settings                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier_price_snapshots     ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplier_price_monitor_runs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_snapshots               ENABLE ROW LEVEL SECURITY;
ALTER TABLE blocked_ips                  ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 검증(음성 테스트) — Phase 0 완료 기준:
--  1) authenticated 롤로 타 user_id row SELECT -> 0건 반환
--  2) authenticated 롤로 타 user_id INSERT/UPDATE -> 거부(WITH CHECK 위반)
--  3) service_role 로는 전체 접근 가능(백엔드 동작 보장)
--  (tests/rls_negative_test.sql 또는 마이그레이션 스크립트의 verify 단계에서 수행)
-- ============================================================
