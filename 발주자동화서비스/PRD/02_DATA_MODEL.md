# 브랜드리셀OS — 데이터 모델

> 이 문서는 앱에서 다루는 핵심 데이터의 구조를 정의합니다.
> 개발자가 아니어도 이해할 수 있는 "개념적 ERD"입니다.
> DB: Supabase (PostgreSQL + RLS). 모든 테이블에 workspace_id 포함(멀티테넌트 대비).

---

## 전체 구조

```
[워크스페이스] --1:N--> [멤버(역할)]
[워크스페이스] --1:N--> [연동계정] (무신사×N, 크림×N, 포이즌×N ...)
[워크스페이스] --1:N--> [구매내역] --N:1--> [연동계정]
                           |--N:1--> [상품]
                           └--N:1--> [입고박스] --1:N--> [입고품목]
[상품] --1:N--> [시세스냅샷] (사이즈·플랫폼별)
[상품] --1:N--> [체결가이력]
[수수료규칙] (플랫폼·카테고리·기간별, 상품과 매칭)
[워크스페이스] --1:N--> [도매분석] --1:N--> [도매분석행] --N:1--> [상품]
[워크스페이스] --1:N--> [판매주문] --N:1--> [연동계정]
```

---

## 엔티티 상세

### 워크스페이스 (workspaces)
한 사업체(팀)의 데이터 울타리. Phase 1엔 1개만 존재하지만 처음부터 만들어 둔다.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 (자동) | ws_abc123 | O |
| name | 사업체 이름 | 홍대상사 | O |
| created_at | 만든 날짜 (자동) | 2026-07-04 | O |

### 멤버 (members)
워크스페이스에 속한 사람과 역할. 영상 핵심: "대표·직원·창고 관리자가 나눠 쓴다."

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 | mb_001 | O |
| workspace_id | 소속 워크스페이스 | ws_abc123 | O |
| user_id | Supabase Auth 사용자 | (auth.users 참조) | O |
| role | owner / staff / warehouse | staff | O |

### 연동계정 (linked_accounts)
구매처·판매처 계정. **플랫폼당 무제한**(셀러는 10~20개 운영).

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 | la_001 | O |
| platform | musinsa / 29cm / lotteon / ssf / kream / kream_biz / poizon / soldout | musinsa | O |
| label | 별칭 | musinsa_a01 | O |
| account_type | buy(구매처) / sell(판매처) | buy | O |
| grade | 계정 등급 | 플래티넘 | X |
| mileage | 마일리지 잔액 | 34200 | X |
| next_grade_gap | 다음 등급까지 남은 금액 | 600000 | X |
| credential_ref | Supabase Vault 시크릿 참조 (자격증명 본문은 여기 저장 안 함) | vault:sec_01 | X |

### 상품 (products)
품번(스타일코드) 기준 상품 마스터. 모든 시세·구매·분석이 이 테이블로 모인다.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 | pr_001 | O |
| brand | 브랜드 | 아디다스 | O |
| name | 상품명 | 삼바 OG 클라우드화이트 | O |
| style_code | 품번 (검색 키) | B75806 | O |
| category | 신발/의류/기타 (수수료 규칙 매칭용) | 신발 | O |
| image_url | 대표 이미지 | https://... | X |

### 시세스냅샷 (market_snapshots)
특정 시점의 플랫폼별·사이즈별 시장 상태. "뒷물량"의 근거 데이터.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 | ms_001 | O |
| product_id | 상품 | pr_001 | O |
| platform | kream / poizon | kream | O |
| size | 사이즈 (전체는 "ALL") | 265 | O |
| lowest_ask | 즉시구매가(최저 판매입찰) | 48000 | X |
| highest_bid | 즉시판매가(최고 구매입찰) | 46000 | X |
| total_listings | 총매물 수 (뒷물량) | 3000 | X |
| monthly_sales | 월 판매량 (KR은 kream행, CN은 poizon행) | 300 | X |
| source | manual / extension / crawler | manual | O |
| captured_at | 수집 시각 | 2026-07-04 09:00 | O |

### 체결가이력 (price_history)
그래프·역대최저가용 시계열. 스냅샷과 분리해 가볍게 유지.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| product_id + size + platform | 대상 | pr_001/265/kream | O |
| price | 체결가 | 47500 | O |
| traded_at | 체결 시각 | 2026-07-03 | O |

### 수수료규칙 (fee_rules)
마진 계산 엔진의 심장. 크림 2026-03 개편(기본 2,500원 + 등급 5.5~6%) + 카테고리 수수료 이벤트를 기간으로 관리.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| platform | kream / poizon | kream | O |
| match | 적용 대상 (전체/카테고리/브랜드/품번) | brand=나이키,cat=신발 | O |
| base_fee | 기본 수수료(원) | 2500 | O |
| rate_pct | 정률 수수료(%) — 등급 레벨별 | 5.95 | O |
| valid_from / valid_to | 적용 기간 (이벤트 대응) | 2026-06-01~07-31 | O |
| memo | 근거 | 나이키 수수료 이벤트 | X |

### 구매내역 (purchases)
장부의 원장. 영상: 날짜·구매처/계정·상품·옵션·결제금액·배송지.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 | pu_001 | O |
| account_id | 구매 계정 | la_001 | O |
| product_id | 매칭된 상품 (미매칭 허용) | pr_001 | X |
| raw_name | 원문 상품명 | 아디다스 저지 IW3427 | O |
| option / qty | 옵션·수량 | L / 2 | O |
| paid_total | 실결제금액 | 74600 | O |
| ship_to | 배송지 | 본사창고 | O |
| is_personal | 개인용 구매 (장부 제외) | false | O |
| status | ordered / shipping / delivered | shipping | O |
| source | manual / paste / csv / extension | paste | O |
| ordered_at | 주문일 | 2026-07-02 | O |

### 입고박스 (inbound_parcels)
운송장 1건 = 박스 1개. 상태 파이프라인의 단위.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| id | 고유 식별자 | ib_001 | O |
| tracking_no | 운송장번호 (스캔 키) | 6889-4512-3302 | O |
| carrier | 택배사 | CJ | X |
| expected_date | 도착 예정일 | 2026-07-04 | X |
| status | expected / arrived / inspecting / completed / issue | arrived | O |
| arrived_by / arrived_at | 도착 스캔 처리자·시각 (감사로그) | 김직원 09:12 | X |
| inspected_by / inspected_at | 검수 처리자·시각 | 김직원 09:31 | X |

### 입고품목 (inbound_items)
박스 안에 들어있어야 할 주문과 실제 검수 결과.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| parcel_id | 소속 박스 | ib_001 | O |
| purchase_id | 매핑된 구매 건 | pu_001 | O |
| expected_qty / received_qty | 기대·실수령 수량 | 2 / 2 | O |
| condition | ok / short(수량부족) / wrong(오배송) / defect(불량) | ok | O |

### 판매주문 (sales_orders) — Phase 2
크림·솔드아웃 다계정 판매 주문 통합.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| account_id | 판매 계정 | la_009 | O |
| product_id / size | 판매 상품 | pr_001 / 265 | O |
| sale_price | 판매가 | 82000 | O |
| ship_deadline | 발송 기한 | 2026-07-05 | O |
| status | pending / shipped | pending | O |
| tracking_no | 발송 송장 (스캔 입력) | 5210-... | X |
| source | excel / api | excel | O |

### 도매분석 (wholesale_analyses / _rows) — Phase 2
스크린샷 → AI 추출 결과. 행 단위 수동 수정 가능해야 함.

| 필드 | 설명 | 예시 | 필수 |
|------|------|------|------|
| image_path | 원본 스크린샷 (Supabase Storage) | storage:/wa/01.png | O |
| status | analyzing / done / failed | done | O |
| (행) style_code / wholesale_price / qty_by_size | AI 추출값 | IE0906 / 68000 / {"265":120,...} | O |
| (행) confidence | AI 확신도 (낮으면 노란 하이라이트) | 0.92 | O |
| (행) product_id | 시세 매칭 결과 | pr_001 | X |

---

## 왜 이 구조인가

- **workspace_id 전면 도입**: Phase 1은 혼자 쓰지만, Supabase RLS 정책을 처음부터 workspace 기준으로 걸면 Phase 3 상용화 때 스키마 변경이 없다.
- **시세스냅샷과 체결가이력 분리**: "지금 상태"(매물·판매량)와 "시계열"(그래프)은 갱신 주기·용량 특성이 달라서 분리. source 필드로 수동→확장→크롤러로 수급 방식이 진화해도 스키마 불변.
- **수수료를 데이터(fee_rules)로**: 크림은 2026-03에 수수료를 개편했고 수시로 카테고리 이벤트를 연다. 코드에 하드코딩하면 매번 배포해야 하므로 기간제 규칙 테이블로.
- **박스(parcel)와 품목(item) 분리**: 영상의 2단계 검수(문앞 도착 스캔 = 박스 단위, 사무실 검수 = 품목 단위)를 그대로 반영.
- **자격증명은 Vault로**: linked_accounts에는 참조만 저장. 비밀번호·토큰 본문은 Supabase Vault(인증된 암호화)에.

---

## [NEEDS CLARIFICATION]

- [ ] 크림 "총매물"을 사이즈별로 수집 가능한지(수동 입력 시 ALL만 기록할지) — 수급 방식 확정 후 결정
- [ ] 판매주문의 플랫폼별 필드 차이(크림 개인 vs 입점사업자 vs 솔드아웃) — Phase 2 진입 시 실데이터로 확정
- [ ] 환율(포이즌 위안화) 처리: 고정 환율 입력 vs 일일 환율 API
