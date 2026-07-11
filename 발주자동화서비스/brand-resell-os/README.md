# 브랜드리셀OS (Phase 1 MVP)

리셀/브랜드유통 셀러용 소싱·장부·입고 관리 웹앱. 벤치마크 = 넘버원 셀러센터.
설계 문서: [`../PRD/`](../PRD/README.md)

## 기능 (Phase 1)

- **시세·마진 계산** (`/sourcing`): 상품 등록 → 크림 시세 수동 입력 → 마진율·적자경고·소진개월 자동 계산
- **구매내역** (`/ledger/purchases`): 수동 등록 + 붙여넣기 가져오기 + 개인용 구분 + 운송장 등록→입고 연결
- **입고 관리** (`/ledger/inbound`): 도착예정→도착→검수→완료/이슈 파이프라인
- **📱 모바일 스캔** (`/m/scan`): 카메라 바코드로 송장 도착 처리 + 검수 (zxing-wasm)
- **계정 연동** (`/settings`): 구매처/판매처 계정 등급·마일리지 수동 기록

## 기술 스택

Next.js 16 (App Router) · TypeScript · Tailwind CSS 4 · Supabase(Auth/DB/RLS) · zxing-wasm

## 로컬 실행

```bash
npm install
npm run dev       # http://localhost:3000
npm run test      # 마진 엔진 단위 테스트 (vitest)
npm run build     # 프로덕션 빌드
```

`.env.local` 필요 (이미 설정됨): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`

## ⚠️ 최초 1회: Supabase 로그인 URL 설정 (30초)

매직링크 로그인이 되려면 Supabase 대시보드에서 리다이렉트 URL을 허용해야 합니다.

1. [Supabase 대시보드](https://supabase.com/dashboard/project/eykzzbjmahdhbgygwnhn/auth/url-configuration) → **Authentication → URL Configuration**
2. **Site URL**: `http://localhost:3000` (배포 후엔 Vercel URL)
3. **Redirect URLs**에 추가: `http://localhost:3000/**` (배포 후 `https://<앱>.vercel.app/**`도 추가)
4. 저장

이후 `/login`에서 이메일 입력 → 받은 메일의 링크 클릭 → 첫 로그인 시 워크스페이스 + 데모 데이터 자동 생성.

## 배포 (Vercel, 무료)

```bash
npm i -g vercel
vercel login          # 본인 계정 로그인 (사용자 직접)
vercel                # 최초 배포 (프로젝트 연결)
# Vercel 대시보드 → Settings → Environment Variables 에
#   NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY 추가
vercel --prod         # 프로덕션 배포
```

배포 후 Supabase URL Configuration에 Vercel 도메인도 추가하면 폰에서 접속(HTTPS)해 카메라 스캔까지 사용 가능.

## 데이터 모델 / RLS

Supabase 프로젝트 `brand-resell-os` (ap-northeast-2). 10개 테이블 모두 `workspace_id` + RLS로 격리.
스키마 상세: [`../PRD/02_DATA_MODEL.md`](../PRD/02_DATA_MODEL.md)
