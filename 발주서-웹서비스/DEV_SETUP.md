# 발주서 웹서비스 (단하루/rj-balju) — 다른 PC에서 작업하기

> 이 문서 하나로 어느 PC(또는 AI 세션)에서든 소스를 받아 수정·배포할 수 있다.
> **다른 세션이 "rj-balju 레포를 못 찾겠다"고 하면 이 문서의 소스 위치를 알려주면 된다.**

## 소스 위치 (가장 중요 — 헷갈리지 말 것)

| 항목 | 값 |
|---|---|
| GitHub 레포 | `github.com/kotkim8210/the-reabon-youtube-blog` (레포 이름이 "rj-balju"가 **아님** — 유튜브블로그 레포에 얹혀 있음) |
| 브랜치 | **`claude/balju-saas-phase0`** ← 실제 작업/배포 브랜치. (`main`은 옛날 빈 커밋이니 쓰지 말 것) |
| 소스 폴더 | 클론 후 **`발주서-웹서비스/`** 하위 (backend/ + frontend/) |
| 배포 대상 | Fly.io 앱 `rj-balju` → https://rj-balju.fly.dev |

* GitHub 기본 브랜치를 `claude/balju-saas-phase0`로 지정해 뒀으므로, 그냥 `git clone` 하면 최신 소스가 받아진다.
* 시크릿(API 키·토큰)은 git에 **없다**(fly secrets에만 있음). 로컬 실행/배포 시 별도 주입 필요(아래).

## ⚠️ 개인용 ↔ 서비스 분리 (2026-07 확정 — 절대 혼동 금지)

같은 코드베이스, **2개 Fly 앱 + 2개 브랜치**로 완전 분리. 개인용은 매일 실사용 중이라 건드리면 안 됨.

| 구분 | 브랜치 | Fly 앱 (fly config) | 배포 명령 | 성격 |
|---|---|---|---|---|
| **개인용** | `claude/balju-saas-phase0` (기본) | `rj-balju` (`fly.toml`) → rj-balju.fly.dev | `fly deploy` | 김광은 실사용. **frozen** — 개인 요청 있을 때만 손댐 |
| **서비스(SaaS)** | `saas` | `danharu-ops-hub` (`fly.danharu.toml`) → danharu-ops-hub.fly.dev | `fly deploy -c fly.danharu.toml` | 상용화 개발 전용 |

- **DB·시크릿·도메인은 앱별로 완전 격리.** 특히 서비스 앱(danharu-ops-hub)에는 개인 쿠팡/토스/Gmail 시크릿을 **일부러 제거**해 뒀다(SECRET_KEY·TEAM_PASSWORD만 유지) → 서비스 개발/테스트가 개인 판매계정을 절대 못 건드림. 서비스가 외부 API를 쓰려면 **서비스 전용 테스트 계정**을 별도로 넣어야 함.
- SaaS 작업은 `git checkout saas` 후 진행하고 `fly deploy -c fly.danharu.toml`로만 배포. **개인용 rj-balju에는 SaaS 코드를 배포하지 않는다.**
- 두 브랜치는 2026-07-14 커밋 `4abe0de4`에서 분기(공통 안정 상태). 이후 divergent.

## 받기

```bash
git clone https://github.com/kotkim8210/the-reabon-youtube-blog rj-balju
cd rj-balju/발주서-웹서비스        # ← 여기가 프로젝트 루트
```

## 대부분의 작업 = 코드 수정 + 배포 (로컬 실행 불필요)

앱은 이미 https://rj-balju.fly.dev 에 떠 있다. 사용자는 브라우저로 쓰고,
개발은 "코드 고치고 → `fly deploy` → 웹 새로고침" 흐름이면 충분하다. 로컬 서버를 띄울 필요가 거의 없다.

### 배포 (Fly.io)
```bash
# 1회: 이 PC에서 Fly 로그인 (flyctl 설치 후)
fly auth login
# 배포 (발주서-웹서비스 폴더에서, fly.toml 있는 곳)
fly deploy
```
* flyctl 미설치 시: https://fly.io/docs/flyctl/install/
* 이 레포 특성상 git 루트가 홈 디렉터리일 수 있으니, 커밋 시 **`git add -A` 금지** — 바꾼 파일만 명시적으로 `git add <경로>` 하고 `git push origin claude/balju-saas-phase0`.

## (선택) 로컬 실행 — 코드를 직접 돌려보고 싶을 때만

시크릿이 필요하다. `.env.example`을 복사해 실제 값(쿠팡/토스/PBF/Gmail 앱비번/JWT 등)을 채운다.
값은 Fly 대시보드의 secrets 또는 담당자(본인)만 안다.

```bash
# 백엔드 (Python 3.11+)
cd backend
python -m venv .venv && . .venv/Scripts/activate   # (mac/linux: source .venv/bin/activate)
pip install -r requirements.txt
cp ../.env.example .env   # 값 채우기
uvicorn app.main:app --reload --port 8000

# 프론트엔드 (Node 18+)
cd ../frontend
npm install
npm run dev
```

## 테스트

```bash
cd backend
python -m pytest -q            # 전체 테스트 (규칙엔진·발주·운송장 매칭 등)
```

## 구조 한눈에

```
발주서-웹서비스/
├─ fly.toml                 # Fly 배포 설정 (앱: rj-balju)
├─ backend/app/
│   ├─ main.py              # FastAPI 엔드포인트
│   ├─ processors/          # 발주서 생성·운송장 매칭 (거래처별)
│   ├─ rules_engine.py      # 규칙 엔진(Phase 1-A) — 상품 매칭 규칙 DB화
│   ├─ supplier_price_monitor.py  # 마진방어
│   └─ routes/              # 인증·결제·규칙·대시보드 API
└─ frontend/src/pages/      # 발주 화면들 (React)
```
