# 발주서-웹서비스 프로젝트 사양서

> **목적:** 이 문서는 현재 구현된 모든 기능을 정리하여 새 기능 추가, 타 AI 협업, 또는 재구성 시 참조용으로 사용합니다.
> **최종 업데이트:** 2026-04-23

---

## 1. 프로젝트 개요

### 서비스명
RJ Systems — 산지직송 발주서/운송장 자동화 SaaS

### 기술 스택
| 레이어 | 기술 |
|--------|------|
| Backend | Python 3.11 + FastAPI + SQLite |
| Frontend | React 18 + TypeScript + Tailwind CSS + React Router |
| DB | SQLite (fly.io Volume: `/data/suyikolla.db`) |
| 외부 API | 쿠팡 Open API, 토스쇼핑 API, 토스페이먼츠 API |
| 인증 | JWT (HS256) + OAuth2 (카카오, 구글) |
| 배포 | Docker (multi-stage) + Fly.io (`rj-balju.fly.dev`) |
| 파일처리 | openpyxl (Excel 읽기/쓰기) |

### 기본 디렉터리 구조
```
발주서-웹서비스/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 진입점 + 파일처리 라우트
│   │   ├── config.py            # 환경변수 설정
│   │   ├── db.py                # SQLite 초기화 + 테이블 정의
│   │   ├── auth.py              # JWT 인증 유틸
│   │   ├── scheduler.py         # 백그라운드 스케줄러 (쿠팡 캐시 갱신 등)
│   │   ├── routes/
│   │   │   ├── auth.py          # 로그인/회원가입/OAuth
│   │   │   ├── admin.py         # 관리자 (유저/IP 관리)
│   │   │   ├── billing.py       # 구독/결제 (토스페이먼츠)
│   │   │   ├── dashboard.py     # 대시보드 데이터
│   │   │   ├── products.py      # 쿠팡 상품 캐시 조회
│   │   │   ├── pricing.py       # 가격 룰 & 마진 관리
│   │   │   ├── sales.py         # 판매 분석
│   │   │   ├── tenant.py        # 멀티테넌트 상품/템플릿 관리
│   │   │   └── toss.py          # 토스쇼핑 주문/CS 관리
│   │   └── processors/
│   │       ├── kolrabi_order.py
│   │       ├── chamdureup_order.py
│   │       ├── chamdureup_tracking.py
│   │       ├── myeongi_order.py
│   │       ├── myeongi_tracking.py
│   │       ├── tomato_order.py
│   │       ├── tomato_tracking.py
│   │       ├── goguma_order.py
│   │       ├── goguma_auto.py
│   │       ├── goguma_tracking.py
│   │       ├── goguma_tracking_alwayz.py
│   │       ├── goguma_tracking_api.py
│   │       ├── toss_auto.py
│   │       ├── tracking_input.py
│   │       ├── gaegeolmu_order.py
│   │       ├── gaegeolmu_tracking.py
│   │       └── generic_order.py
│   ├── templates/               # Excel 템플릿 파일
│   ├── static/                  # 빌드된 React 앱 (배포 시)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.tsx              # 라우터 + 전역 인증 상태
│       ├── api.ts               # API 호출 함수 전체
│       ├── index.css
│       ├── pages/
│       │   ├── Login.tsx
│       │   ├── SignupPage.tsx
│       │   ├── PricingPage.tsx
│       │   ├── AdminPanel.tsx
│       │   ├── OrderTools.tsx
│       │   ├── BatchTrackingPage.tsx   ← 일괄 운송장 입력 (신규)
│       │   ├── ToolSettings.tsx
│       │   ├── ProcessPage.tsx
│       │   ├── GogumaUnifiedPage.tsx
│       │   ├── GogumaAutoPage.tsx
│       │   ├── TossAutoPage.tsx
│       │   ├── UnifiedProcessPage.tsx
│       │   ├── TenantProductConfig.tsx
│       │   ├── TenantOrderPage.tsx
│       │   ├── PricingDashboard.tsx
│       │   ├── SalesDashboard.tsx
│       │   ├── BillingDashboard.tsx
│       │   └── NotFound.tsx
│       ├── components/
│       │   ├── AppShell.tsx     # 사이드바 + 네비게이션 레이아웃
│       │   ├── FileUpload.tsx   # 파일 드래그앤드롭 컴포넌트
│       │   ├── ProcessCard.tsx  # 도구 선택 카드
│       │   ├── AdminModal.tsx
│       │   └── mvp/
│       │       ├── DashboardHome.tsx
│       │       ├── PlaceholderTab.tsx
│       │       └── SidebarItem.tsx
│       └── lib/
│           └── toolCatalog.ts   # 도구 목록 + 사용자 숨김/삭제 설정
├── Dockerfile                   # multi-stage: node(프론트) + python(백엔드)
├── fly.toml                     # Fly.io 배포 설정
└── PROJECT_SPEC.md              # 이 파일
```

---

## 2. 인증 시스템

### 방식
- JWT (Bearer Token) — 7일 유효
- `Authorization: Bearer <token>` 헤더로 전달

### 역할
| 역할 | 권한 |
|------|------|
| `admin` | 전체 접근 + 유저/IP 관리 |
| `pro` | 모든 파일처리 + 대시보드 + 분석 |
| `free` | 기본 파일처리만 (월 50건 제한) |

### 엔드포인트 (`/api/auth/*`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/auth/config` | 인증 비활성화 여부 확인 |
| GET | `/api/auth/oauth-config` | 카카오/구글 클라이언트 ID |
| POST | `/api/auth/signup` | 회원가입 |
| POST | `/api/auth/login` | 이메일+비밀번호 로그인 |
| POST | `/api/auth/change-password` | 비밀번호 변경 |
| POST | `/api/auth/kakao/token` | 카카오 OAuth 토큰 교환 |
| POST | `/api/auth/google/token` | 구글 OAuth 토큰 교환 |
| GET | `/api/auth/me` | 현재 사용자 정보 |

---

## 3. 파일 처리 기능 (핵심)

### 처리 흐름
```
사용자 → 파일 업로드(Excel) → POST /api/process/{toolId}
       → 백엔드 processor 실행
       → 매핑/변환
       → 결과 Excel 다운로드
       → X-Stats 헤더로 통계 반환
```

### 응답 형식
- **Content-Type:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **Content-Disposition:** `attachment; filename*=UTF-8''파일명.xlsx`
- **X-Stats:** `{"filled": 12, "skipped": 2}` (JSON)

### 발주서 처리 (Order)

| toolId | 거래처 | 입력 파일 | 출력 |
|--------|--------|----------|------|
| `kolrabi-order` | 콜라비 (제주다팜) | DeliveryList | 발주서 Excel |
| `chamdureup-order` | 참두릅 | DeliveryList | 발주서 Excel |
| `myeongi-order` | 명이나물 | DeliveryList | 발주서 Excel |
| `tomato-order` | 대저토마토·성주참외·남해땅두릅 | DeliveryList | 발주서 Excel |
| `goguma-order` | 고구마 (해달) | DeliveryList + (선택)템플릿 + (선택)알웨이즈 + (선택)토스 | 발주서 Excel |
| `goguma-auto` | 고구마 (자동) | API (날짜범위만 입력) | 발주서 Excel |
| `gaegeolmu-order` | 게걸무씨앗기름 | DeliveryList | 발주서 Excel |
| `toss-order` | 토스쇼핑 | API (날짜범위) | 발주서 Excel |

### 운송장 처리 (Tracking)

| toolId | 거래처 | 입력 파일 (key명) | 매핑 방식 |
|--------|--------|-----------------|---------|
| `tracking-input` | 콜라비 (범용) | `orderlist_file` + `delivery_file` | 이름+전화번호+주소 |
| `chamdureup-tracking` | 참두릅 | `orderlist_file` + `delivery_file` | 주문번호 우선 → 이름 폴백 |
| `myeongi-tracking` | 명이나물 | `orderlist_file` + `delivery_file` | 이름+전화번호+주소 |
| `tomato-tracking` | 대저토마토·성주참외·남해땅두릅 | `tomato_reply_file` + `delivery_file` | 이름+택배사(K열) |
| `goguma-tracking` | 고구마 (범용) | `haedal_file` + `delivery_file` | P~V열 동적 운송장 탐색 |
| `goguma-tracking-api` | 고구마 (API 등록) | `haedal_file` | 쿠팡 API 직접 등록 |
| `goguma-tracking-alwayz` | 고구마 (알웨이즈) | `haedal_file` + `alwayz_file` | 알웨이즈 운송장 매핑 |
| `toss-tracking-api` | 토스 (API 등록) | `haedal_file` | 토스 API 직접 등록 |
| `gaegeolmu-tracking` | 게걸무씨앗기름 | `tracking_file` + `delivery_file` | 이름(B열)+운송장(C열) |

### 일괄 운송장 입력 (신규)
- **경로:** `/orders/batch-tracking`
- **설명:** 고구마를 제외한 5개 거래처 파일을 한 화면에서 올리고 한 번에 처리
- **지원 거래처:** 참두릅, 명이나물, 콜라비, 대저토마토·성주참외·남해땅두릅, 게걸무씨앗기름

---

## 4. DeliveryList 파일 구조 (공통)

모든 발주서 처리의 기준 파일. 쿠팡 셀러센터에서 다운로드.

| 열 | 내용 |
|----|------|
| AA | 수취인 이름 |
| AB | 수취인 전화번호 |
| AD | 수취인 주소 |
| E  | 운송장번호 (처리 후 채워짐) |
| K  | 상품명 / 택배사명 (거래처별 상이) |

---

## 5. 멀티테넌트 커스텀 상품 처리

일반 사용자가 자체 상품/옵션을 정의하여 DeliveryList에서 자동 추출.

### 설정 흐름
1. `/my/products` — 템플릿 업로드 + 상품/옵션 키워드 정의
2. `/my/process` — DeliveryList 업로드 → 상품별 Excel 또는 ZIP 다운로드

### 엔드포인트 (`/api/tenant/*`)
| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/tenant/templates` | 템플릿 업로드 |
| GET | `/api/tenant/templates` | 템플릿 목록 |
| DELETE | `/api/tenant/templates/{id}` | 템플릿 삭제 |
| POST | `/api/tenant/products` | 커스텀 상품 생성 |
| GET | `/api/tenant/products` | 상품 목록 |
| PUT | `/api/tenant/products/{id}` | 상품 수정 |
| DELETE | `/api/tenant/products/{id}` | 상품 삭제 |
| POST | `/api/tenant/analyze` | 배송 파일 분석 (상품/옵션명 추출) |
| POST | `/api/tenant/process` | 배송 파일 처리 + Excel 다운로드 |

---

## 6. 쿠팡 연동 & 대시보드

### 자동 갱신 (백그라운드 스케줄러)
- 매 1시간: 쿠팡 상품 목록 갱신 → `cached_products`
- 매 2시간: 쿠팡 최근 주문 갱신 → `cached_orders`, `daily_sales`
- 매일 자정: 구독 갱신 처리

### 대시보드 엔드포인트 (`/api/dashboard/*`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/dashboard/summary` | 주문/재고 요약 |
| GET | `/api/dashboard/recent-orders` | 최근 20건 주문 |
| GET | `/api/dashboard/risk-scores` | 재고/마진 위험 신호등 |
| GET | `/api/dashboard/inventory-alerts` | 재고 부족 알림 |
| POST | `/api/dashboard/refresh` | 수동 갱신 |

---

## 7. 가격/마진 관리

### 기능
- 상품별 최소마진%, 최저가, 최고가, 광고중단임계값 설정
- 드라이런 가격제안 (실제 변경 없이 시뮬레이션)
- 가격 변경 이력 로그

### 엔드포인트 (`/api/pricing/*`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/pricing/rules` | 룰 목록 |
| POST | `/api/pricing/rules` | 룰 생성/수정 |
| DELETE | `/api/pricing/rules/{product_id}` | 룰 비활성화 |
| GET | `/api/pricing/proposals` | 가격제안 목록 |
| GET | `/api/pricing/margins` | 전체 상품 마진 현황 |
| GET | `/api/pricing/log` | 가격 변경 이력 |

---

## 8. 판매 분석

### 기능
- 옵션별 일/월 판매량/매출
- 판매 트렌드 차트
- 일별 정산 카드

### 엔드포인트 (`/api/sales/*`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/sales/summary` | 옵션별 판매 요약 |
| GET | `/api/sales/trend` | 옵션별 판매 트렌드 |
| GET | `/api/sales/settlement-cards` | 일별 정산 데이터 |

---

## 9. 구독 & 결제 (SaaS)

### 플랜
| 플랜 | 월 비용 | 제한 |
|------|---------|------|
| free | 무료 | 월 50건, 기본 파일처리만 |
| pro | 29,000원 | 월 3,000건, 전체 기능 |

### 결제 방식: 토스페이먼츠 자동결제
1. 첫 결제: 카드 빌링키 발급
2. 웹훅: 결제 완료 확인 → 구독 활성화
3. 갱신: 매월 자동결제 스케줄러

### 엔드포인트 (`/api/billing/*`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/billing/plans` | 플랜 목록 |
| GET | `/api/billing/config` | 토스 결제 설정 |
| GET | `/api/billing/subscription` | 내 구독 상태 |
| POST | `/api/billing/subscribe` | 구독 시작/변경 |
| POST | `/api/billing/cancel` | 구독 해지 예약 |
| POST | `/api/billing/resume` | 해지 취소 |
| POST | `/api/billing/webhook/toss` | 토스페이먼츠 웹훅 |

---

## 10. 관리자 기능

### 엔드포인트 (`/api/admin/*`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/admin/users` | 전체 유저 목록 |
| POST | `/api/admin/users` | 유저 생성 |
| PATCH | `/api/admin/users/{id}/toggle` | 활성/비활성 토글 |
| GET | `/api/admin/blocked-ips` | 차단 IP 목록 |
| POST | `/api/admin/blocked-ips` | IP 차단 |
| DELETE | `/api/admin/blocked-ips/{id}` | IP 차단 해제 |

---

## 11. 토스쇼핑 연동

### 기능
- 토스쇼핑 주문 조회 (날짜 범위)
- CS 클레임 처리 (취소/교환/반품 승인·거절)
- 토스 발주서 자동 생성

### 엔드포인트 (`/api/toss/*`)
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/toss/orders` | 주문 목록 |
| GET | `/api/toss/claims` | 클레임 목록 |
| POST | `/api/toss/claims/{id}/approve-cancel` | 취소 승인 |
| POST | `/api/toss/claims/{id}/reject-cancel` | 취소 거절 |
| POST | `/api/toss/claims/{id}/approve-exchange` | 교환 승인 |
| POST | `/api/toss/claims/{id}/reject-exchange` | 교환 거절 |
| POST | `/api/toss/claims/{id}/approve-return` | 반품 승인 |
| POST | `/api/toss/claims/{id}/reject-return` | 반품 거절 |

---

## 12. 데이터베이스 스키마

| 테이블 | 목적 |
|--------|------|
| `users` | 사용자 계정 (id, username, password_hash, email, google_id, kakao_id, role, is_active) |
| `blocked_ips` | IP 차단 목록 |
| `app_settings` | 키-값 앱 설정 (team_password 등) |
| `cached_products` | 쿠팡 상품 캐시 (seller_product_id, product_name, sale_price, stock) |
| `cached_orders` | 쿠팡 주문 캐시 (order_id, product_name, quantity, status) |
| `daily_sales` | 일별 판매량 집계 |
| `option_sales` | 옵션별 일별 판매 (판매 분석용) |
| `risk_snapshots` | 재고/마진 위험도 스냅샷 |
| `pricing_rules` | 가격 룰 (min_margin_pct, min_price, max_price) |
| `pricing_log` | 가격 변경 이력 |
| `plans` | 구독 플랜 정의 (free, pro) |
| `subscriptions` | 유저별 구독 상태 + 빌링키 |
| `billing_events` | 결제 이벤트 로그 |
| `usage_logs` | 월별 사용량 추적 |
| `user_templates` | 유저 커스텀 Excel 템플릿 |
| `user_products` | 유저 커스텀 상품 정의 |
| `user_product_options` | 상품별 옵션 매핑 |

---

## 13. 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `SECRET_KEY` | change-me | JWT 서명 키 |
| `TEAM_PASSWORD` | rjsystems2024 | 레거시 팀 비밀번호 |
| `AUTH_DISABLED` | false | 인증 비활성화 (개발용) |
| `DATABASE_PATH` | /data/suyikolla.db | SQLite 경로 |
| `DEPLOYMENT_MODE` | saas | saas / onprem |
| `COUPANG_VENDOR_ID` | | 쿠팡 벤더 ID |
| `COUPANG_ACCESS_KEY` | | 쿠팡 API 키 |
| `COUPANG_SECRET_KEY` | | 쿠팡 API 시크릿 |
| `TOSS_ACCESS_KEY` | | 토스쇼핑 클라이언트 ID |
| `TOSS_SECRET_KEY` | | 토스쇼핑 시크릿 |
| `TOSS_PAY_SECRET_KEY` | | 토스페이먼츠 시크릿 |
| `TOSS_PAY_CLIENT_KEY` | | 토스페이먼츠 클라이언트 키 |
| `APP_BASE_URL` | http://localhost:5173 | 프론트엔드 URL |
| `KAKAO_CLIENT_ID` | | 카카오 OAuth JS 키 |
| `GOOGLE_CLIENT_ID` | | 구글 OAuth 클라이언트 ID |
| `PRO_PLAN_PRICE` | 29000 | Pro 플랜 월 금액 (원) |
| `DISABLE_SIGNUP` | false | 회원가입 차단 |
| `DISABLE_BILLING` | false | 결제 비활성화 |
| `DISABLE_QUOTA` | false | 사용량 제한 비활성화 |

---

## 14. 새 거래처 추가 방법 (패턴)

### Step 1. 백엔드 프로세서 생성
`backend/app/processors/새거래처_order.py`:
```python
import io
import openpyxl
from datetime import datetime

def process(delivery_bytes: bytes) -> tuple[bytes, str, dict]:
    wb_in = openpyxl.load_workbook(io.BytesIO(delivery_bytes))
    ws = wb_in.active
    
    # DeliveryList에서 해당 거래처 행 추출
    # AA열=이름, AB열=전화번호, AD열=주소, K열=상품명
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[10] and "새거래처키워드" in str(row[10]):
            rows.append(row)
    
    # 출력 Excel 생성
    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active
    # ... 데이터 채우기 ...
    
    buf = io.BytesIO()
    wb_out.save(buf)
    filename = f"새거래처_발주서_{datetime.now().strftime('%Y%m%d')}.xlsx"
    stats = {"total": len(rows)}
    return buf.getvalue(), filename, stats
```

### Step 2. main.py에 라우트 추가
```python
@app.post("/api/process/새거래처-order")
async def 새거래처_order(
    delivery_file: UploadFile = File(...),
    user=Depends(verify_token),
):
    from app.processors import 새거래처_order as proc
    delivery_bytes = await delivery_file.read()
    output, filename, stats = proc.process(delivery_bytes)
    return make_excel_response(output, filename, stats)
```

### Step 3. 프론트엔드 ProcessPage.tsx toolConfigs에 추가
```typescript
'새거래처-order': {
  title: '새거래처 발주서 생성',
  description: '설명...',
  icon: '🌟',
  files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
  color: 'green',
  colorClasses: { bg: 'bg-green-50', text: 'text-green-700', badge: 'bg-green-100 text-green-700' },
},
```

### Step 4. toolCatalog.ts에 추가
```typescript
{
  id: '새거래처-unified',
  title: '새거래처',
  description: '발주서 생성 + 운송장번호 입력',
  icon: '🌟',
  color: 'green',
  kind: 'unified',
},
```

### Step 5. BatchTrackingPage.tsx VENDORS 배열에 추가 (운송장 처리가 있을 경우)
```typescript
{
  id: '새거래처',
  toolId: '새거래처-tracking',
  label: '새거래처',
  icon: '🌟',
  color: { border: 'border-green-200', header: 'bg-green-50', badge: 'bg-green-100 text-green-700', dot: 'bg-green-500' },
  files: [
    { key: 'orderlist', label: 'Orderlist 파일' },
    { key: 'delivery', label: 'DeliveryList 파일' },
  ],
},
```

---

## 15. 프론트엔드 라우트 맵

| 경로 | 컴포넌트 | 인증 필요 | 설명 |
|------|----------|-----------|------|
| `/login` | Login | ❌ | 로그인 |
| `/signup` | SignupPage | ❌ | 회원가입 |
| `/pricing` | PricingPage | ❌ | 요금제 안내 |
| `/` | DashboardHome | ✅ | 메인 대시보드 |
| `/orders` | OrderTools | ✅ | 도구 선택 화면 |
| `/orders/batch-tracking` | BatchTrackingPage | ✅ | 일괄 운송장 입력 |
| `/orders/settings` | ToolSettings | ✅ | 도구 표시 설정 |
| `/process/goguma` | GogumaUnifiedPage | ✅ | 고구마 통합 |
| `/process/goguma-auto` | GogumaAutoPage | ✅ | 고구마 자동발주 |
| `/process/toss-auto` | TossAutoPage | ✅ | 토스 자동발주 |
| `/process/unified/:productId` | UnifiedProcessPage | ✅ | 통합 발주/운송장 |
| `/process/:toolId` | ProcessPage | ✅ | 범용 파일처리 |
| `/my/products` | TenantProductConfig | ✅ | 상품 설정 |
| `/my/process` | TenantOrderPage | ✅ | 커스텀 처리 |
| `/pricing` (auth) | PricingDashboard | ✅ | 마진/가격 관리 |
| `/sales` | SalesDashboard | ✅ | 판매 분석 |
| `/billing` | BillingDashboard | ✅ | 구독/결제 |
| `/admin` | AdminPanel | ✅ Admin | 관리자 패널 |

---

## 16. api.ts 주요 함수 목록

```typescript
// 인증
login(username, password) → {access_token}
fetchMe() → UserMe
checkAuthConfig() → {auth_disabled}
getOAuthConfig() → {kakao_client_id, google_client_id}
loginWithKakao(accessToken) → {access_token}
loginWithGoogle(accessToken) → {access_token}
signup(username, email, password) → {message}

// 파일 처리
processFile(toolId, files, extraValues?) → ProcessResult
downloadBlob(blob, filename) → void

// 대시보드
fetchDashboardSummary() → DashboardSummaryData
fetchRecentOrders() → {orders}
fetchRiskScores() → {scores}
fetchInventoryAlerts() → {alerts}
refreshDashboardData() → {status}

// 상품
fetchProducts() → {products}

// 가격
fetchPricingRules() → {rules}
createPricingRule(rule) → {status}
deletePricingRule(productId) → {status}
fetchPricingProposals() → {proposals}
fetchMargins() → {margins}
fetchPricingLog() → {logs}

// 판매
fetchSalesSummary(params) → SalesSummaryData
fetchSalesTrend(params) → SalesTrendData
fetchSettlementCards(params) → SettlementCardData[]

// 구독
getBillingMe() → BillingMeData
getBillingPlans() → {plans}
getBillingConfig() → {client_key}
subscribePlan(plan_code, ...) → {status}
cancelSubscription() → {status}
resumeSubscription() → {status}

// 테넌트
uploadTemplate(file) → {template_id}
fetchTemplates() → {templates}
deleteTemplate(id) → {status}
createProduct(data) → {product}
fetchUserProducts() → {products}
updateProduct(id, data) → {product}
deleteProduct(id) → {status}
analyzeDelivery(file) → {items}
processTenant(file) → ProcessResult

// 관리자
fetchAdminUsers() → {users}
createAdminUser(data) → {user}
toggleUserActive(id) → {status}
fetchBlockedIps() → {blocks}
blockIp(data) → {block}
unblockIp(id) → {status}
```

---

## 17. 배포 정보

- **URL:** https://rj-balju.fly.dev
- **Region:** nrt (도쿄)
- **인스턴스:** 1x shared-cpu-1x 512MB
- **스토리지:** Fly Volume `vol_vje0lwygkz751zx4` → `/data`
- **배포 명령:** `fly deploy` (Dockerfile 자동 빌드)
- **시크릿 관리:** `fly secrets set KEY=VALUE`

### 현재 Fly 시크릿 목록
- `SECRET_KEY` — JWT 서명 키
- `TEAM_PASSWORD` — 팀 비밀번호
- `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`, `COUPANG_VENDOR_ID`
- `TOSS_ACCESS_KEY`, `TOSS_SECRET_KEY`
- `TOSS_PAY_SECRET_KEY`, `TOSS_PAY_CLIENT_KEY`
- `AUTH_DISABLED` — 현재 `false`
