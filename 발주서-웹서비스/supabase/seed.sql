-- ============================================================
--  발주서 자동화 SaaS — 시드 데이터 (Phase 0)
--  기존 db.py init_db() 시드와 동일: plans(free/pro)
--  실행: schema.sql -> rls_policies.sql 이후
--  ※ admin 유저/team_password 는 환경별 비밀값이므로 시드에 넣지 않음
--    (배포 환경에서 별도 설정. Phase 3 Supabase Auth 전환 시 재정의)
-- ============================================================

-- 요금제 (현행 2단). 4단 확장(Starter/Business)은 02-monetization-pricing.md 참조,
-- features_json 키 추가 + INSERT 로 추후 무중단 확장 가능.
INSERT INTO plans (code, name, price_krw, max_products, max_monthly_orders, features_json, active)
VALUES
    ('free', '무료', 0, 1, 50,
     '{"tracking": false, "coupang_api": false, "pricing": false, "sales_history_days": 30}', 1),
    ('pro', 'Pro', 29000, NULL, 3000,
     '{"tracking": true, "coupang_api": true, "pricing": true, "sales_history_days": null}', 1)
ON CONFLICT (code) DO NOTHING;

-- 시퀀스 동기화: 데이터 이전(명시 id 삽입) 이후 IDENTITY 시퀀스를 max(id)+1 로 재설정해야
-- 신규 INSERT 시 PK 충돌이 없다. (migrate 스크립트가 모든 테이블에 대해 수행)
-- 예: SELECT setval(pg_get_serial_sequence('plans','id'), COALESCE((SELECT MAX(id) FROM plans), 1));
