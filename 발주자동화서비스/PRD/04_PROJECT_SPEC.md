# 브랜드리셀OS — 프로젝트 스펙

> AI가 코드를 짤 때 지켜야 할 규칙과 절대 하면 안 되는 것.
> 이 문서를 AI에게 항상 함께 공유하세요.

---

## 기술 스택

| 영역 | 선택 | 이유 |
|------|------|------|
| 프레임워크 | Next.js 15 (App Router) + TypeScript | 웹+모바일 반응형 단일 코드베이스, Vercel 무중단 배포, SaaS 보일러플레이트 생태계 최다 |
| DB/백엔드 | Supabase (Postgres + RLS + Auth + Storage + Vault) | 이미 MCP 연결·사용 경험 보유. RLS로 멀티테넌트, Vault로 계정 자격증명 암호화 |
| 배포 | Vercel (웹) + Fly.io (Phase 3 크롤링/수집 워커) | 사용자가 fly.io 운영 경험 보유. Supabase Edge Functions는 헤드리스 브라우저 부적합(리서치 확인) |
| 인증 | Supabase Auth (이메일 매직링크) | 별도 인증 서버 불필요, 역할(owner/staff/warehouse)은 members 테이블로 |
| 스타일링 | Tailwind CSS 4 + shadcn/ui | 와이어프레임의 테이블·칩·파이프라인 UI를 빠르게 조립 |
| 바코드 스캔 | `@sec-ant/barcode-detector` (zxing-wasm 포니필) | **네이티브 BarcodeDetector는 iOS Safari 미지원** — 포니필 기준 설계 필수. 택배 운송장 CODE-128 지원 |
| AI 추출 | Claude API (vision + Structured Outputs, JSON Schema 강제) | 도매 캡처 → 품번/가격/수량 스키마 보장 추출. confidence 필드 + "못 읽으면 null" 프롬프트 패턴 |
| 그래프 | Recharts (또는 lightweight-charts) | 체결가 시계열 + 최저가 기준선 |

---

## 프로젝트 구조

```
brand-resell-os/
├── src/
│   ├── app/
│   │   ├── (auth)/login/          # 매직링크 로그인
│   │   ├── sourcing/              # 시세 비교 · 시세 상세
│   │   ├── sourcing/wholesale/    # 도매 AI 분석 (Phase 2)
│   │   ├── ledger/purchases/      # 구매내역
│   │   ├── ledger/inbound/        # 입고 관리 (PC)
│   │   ├── ledger/outbound/       # 발송 관리 (Phase 2)
│   │   ├── m/scan/                # 모바일 스캔 (도착/검수)
│   │   └── settings/              # 계정 연동 · 멤버/권한
│   ├── components/                # 재사용 UI (칩, 파이프라인, 스캐너)
│   ├── lib/
│   │   ├── supabase/              # 클라이언트/서버 클라이언트, RLS 헬퍼
│   │   ├── margin/                # 마진 계산 엔진 (순수 함수 — 테스트 필수)
│   │   └── scan/                  # barcode-detector 래퍼
│   └── types/
├── supabase/migrations/           # 스키마 마이그레이션 (02_DATA_MODEL.md 기준)
├── .env.local
└── package.json
```

---

## 절대 하지 마 (DO NOT)

> AI에게 코드를 시킬 때 이 목록을 반드시 함께 공유하세요.

- [ ] API 키·비밀번호·계정 자격증명을 코드나 일반 테이블에 직접 쓰지 마 (.env + Supabase Vault만)
- [ ] 네이티브 `window.BarcodeDetector`에만 의존하지 마 — iOS Safari에서 조용히 실패한다. 항상 포니필 경유
- [ ] 크림 등 외부 사이트를 서버에서 자동 크롤링하는 코드를 넣지 마 (Phase 3 법률 검토 전 금지 — PRD §6)
- [ ] 자동 구매(매크로) 기능을 만들지 마 — 스코프 밖, 계정 정지 리스크
- [ ] 마진 계산 로직에 수수료율을 하드코딩하지 마 — 반드시 fee_rules 테이블 경유 (크림은 2026-03에도 개편했다)
- [ ] workspace_id 없는 테이블을 만들지 마, RLS 정책 없이 테이블을 노출하지 마
- [ ] 목업/하드코딩 데이터로 "완성"이라고 하지 마
- [ ] 기존 DB 스키마를 마이그레이션 파일 없이 임의 변경하지 마
- [ ] service_role 키를 클라이언트 번들에 노출하지 마

## 항상 해 (ALWAYS DO)

- [ ] 변경하기 전에 계획을 먼저 보여줘
- [ ] 마진 계산 엔진(lib/margin)은 순수 함수 + 단위 테스트 (영상 예시로 검증: 매입 37,300 → 크림 정산 후 +8,000원대)
- [ ] 모바일 우선: 스캔 화면은 한 손 조작·큰 버튼·진동 피드백, 오프라인 스캔 큐 로컬 저장 후 동기화
- [ ] AI 추출 결과는 항상 사람이 수정 가능한 테이블로 표시 (confidence < 0.8 노란 하이라이트)
- [ ] 입고/발송 처리에 처리자·시각 감사로그 기록
- [ ] 금액은 원 단위 정수(int)로 저장, 표시할 때만 포맷
- [ ] 에러는 사용자 친화적 한국어 메시지로

---

## 테스트 방법

```bash
npm run dev          # 로컬 실행
npx tsc --noEmit     # 타입 체크
npm run test         # 마진 엔진 단위 테스트 (vitest)
npm run build        # 빌드 확인
```
- 스캔 기능은 실제 폰(iOS Safari + Android Chrome)에서 실제 택배 송장으로 검증 — 에뮬레이터 검증은 통과로 치지 않음

## 배포 방법

- 웹: GitHub push → Vercel 자동 배포 (프리뷰 → 프로덕션)
- DB: `supabase migration up` (또는 Supabase MCP `apply_migration`)
- Phase 3 워커: `fly deploy` (기존 발주서 서비스와 동일 패턴)

## 환경변수

| 변수명 | 설명 | 어디서 발급 |
|--------|------|------------|
| NEXT_PUBLIC_SUPABASE_URL | Supabase 프로젝트 URL | supabase.com 대시보드 |
| NEXT_PUBLIC_SUPABASE_ANON_KEY | 공개 anon 키 (RLS 전제) | supabase.com 대시보드 |
| SUPABASE_SERVICE_ROLE_KEY | 서버 전용 키 (클라이언트 노출 금지) | supabase.com 대시보드 |
| ANTHROPIC_API_KEY | Claude vision 추출 (Phase 2) | console.anthropic.com |

> .env.local 파일에 저장. 절대 GitHub에 올리지 마세요.

---

## [NEEDS CLARIFICATION]

- [ ] 스캔 인식률이 현장에서 부족할 경우 상용 SDK(STRICH 등, 연 수백만 원) 도입 여부 — Phase 1 실측 후 결정
- [ ] Supabase 프로젝트: 기존 프로젝트 공용 vs 신규 프로젝트 분리 (추천: 신규 분리)
