import { Link, Navigate } from 'react-router-dom';

const FEATURES = [
  {
    icon: '📦',
    title: '발주서 자동 생성',
    desc: '쿠팡 DeliveryList·토스·테무·올웨이즈 주문을 거래처별 발주서 양식으로 자동 변환. 옵션 매칭·등급 치환·합배송 규칙까지 1분이면 끝.',
  },
  {
    icon: '🚚',
    title: '운송장 자동 등록',
    desc: '거래처 회신 파일을 올리면 수취인 매칭 후 쿠팡·토스에 운송장을 자동 입력. 동명이인 구분, 오입력 방지.',
  },
  {
    icon: '🛡️',
    title: '마진방어 모니터',
    desc: '거래처 공급가를 매일 자동 확인. 단가가 올라 마진이 깨지는 순간 경고 — 모르고 적자 판매하는 일이 사라집니다.',
  },
  {
    icon: '🚫',
    title: '중복발주 방지',
    desc: '이전 영업일에 발주한 주문을 기억해 이중 출고를 차단. 제외된 주문은 받는분 이름까지 표시합니다.',
  },
];

function LandingPage() {
  // 로그인 상태면 대시보드로
  if (localStorage.getItem('token')) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-amber-50/60 via-white to-white text-gray-900">
      {/* 헤더 */}
      <header className="max-w-5xl mx-auto flex items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2 font-extrabold text-lg">
          <span className="text-2xl">🏷️</span> 단하루 발주센터
        </div>
        <nav className="flex items-center gap-3 text-sm font-semibold">
          <Link to="/pricing" className="text-gray-600 hover:text-gray-900 px-3 py-2">요금제</Link>
          <Link to="/login" className="text-gray-600 hover:text-gray-900 px-3 py-2">로그인</Link>
          <Link
            to="/signup"
            className="bg-emerald-600 text-white px-4 py-2 rounded-xl hover:bg-emerald-700 transition-all shadow-sm"
          >
            무료로 시작
          </Link>
        </nav>
      </header>

      {/* 히어로 */}
      <section className="max-w-5xl mx-auto px-6 pt-14 pb-16 text-center">
        <p className="inline-block text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1 mb-5">
          위탁판매(산지직송) 셀러 전용
        </p>
        <h1 className="text-3xl md:text-5xl font-extrabold leading-tight tracking-tight mb-5">
          쿠팡·토스·테무 주문,<br />거래처 발주서로 <span className="text-emerald-600">1분 만에.</span>
        </h1>
        <p className="text-base md:text-lg text-gray-500 max-w-2xl mx-auto mb-8">
          매일 아침 엑셀 수기 변환에 쓰던 1시간을 클릭 한 번으로. 발주서 생성부터
          운송장 자동 등록, 공급가 인상 경고까지 — 실제 셀러가 11개월 운영하며 검증한 자동화입니다.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Link
            to="/signup"
            className="bg-emerald-600 text-white px-7 py-3.5 rounded-2xl font-bold text-base hover:bg-emerald-700 transition-all shadow-lg shadow-emerald-200"
          >
            14일 Pro 무료체험 시작
          </Link>
          <Link
            to="/pricing"
            className="border-2 border-emerald-600 text-emerald-700 px-6 py-3 rounded-2xl font-bold text-base hover:bg-emerald-50 transition-all"
          >
            요금제 보기
          </Link>
        </div>
        <p className="text-xs text-gray-400 mt-4">카드 등록 없이 가입 즉시 체험 · 체험 종료 후 자동결제 없음</p>
      </section>

      {/* 신뢰 지표 (본인 운영 실측) */}
      <section className="max-w-5xl mx-auto px-6 pb-14">
        <div className="grid grid-cols-3 gap-3 max-w-2xl mx-auto text-center">
          {[
            ['1분', '발주서 생성 (기존 30~60분)'],
            ['월 3,000건+', '실운영 처리 주문'],
            ['0건', '운송장 오입력 사고'],
          ].map(([num, label]) => (
            <div key={label} className="bg-white border border-gray-200 rounded-2xl py-5 px-3 shadow-sm">
              <p className="text-xl md:text-2xl font-extrabold text-emerald-600">{num}</p>
              <p className="text-[11px] md:text-xs text-gray-500 mt-1">{label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 기능 4종 */}
      <section className="max-w-5xl mx-auto px-6 pb-16">
        <h2 className="text-xl md:text-2xl font-extrabold text-center mb-8">발주 업무의 처음부터 끝까지</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {FEATURES.map((f) => (
            <div key={f.title} className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm">
              <div className="text-3xl mb-3">{f.icon}</div>
              <h3 className="font-bold text-base mb-1.5">{f.title}</h3>
              <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 요금제 요약 */}
      <section className="max-w-5xl mx-auto px-6 pb-16">
        <h2 className="text-xl md:text-2xl font-extrabold text-center mb-8">단순한 요금제</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl mx-auto">
          <div className="bg-white border border-gray-200 rounded-2xl p-7 shadow-sm">
            <h3 className="font-bold text-lg">Free</h3>
            <p className="text-3xl font-extrabold my-2">₩0</p>
            <ul className="text-sm text-gray-500 space-y-1.5 mb-5">
              <li>· 상품 2개 · 월 주문 300건</li>
              <li>· 발주서 생성 + 운송장 수동 처리</li>
              <li>· 중복발주 방지</li>
            </ul>
            <Link to="/signup" className="block text-center border-2 border-gray-300 rounded-xl py-2.5 font-bold text-sm text-gray-600 hover:bg-gray-50">
              무료로 시작
            </Link>
          </div>
          <div className="bg-white border-2 border-emerald-500 rounded-2xl p-7 shadow-lg shadow-emerald-100 relative">
            <span className="absolute -top-3 left-6 bg-emerald-600 text-white text-[11px] font-bold px-3 py-1 rounded-full">가입 시 14일 무료체험</span>
            <h3 className="font-bold text-lg">Pro</h3>
            <p className="text-3xl font-extrabold my-2">₩29,000<span className="text-sm text-gray-400 font-semibold">/월</span></p>
            <ul className="text-sm text-gray-500 space-y-1.5 mb-5">
              <li>· 상품·주문 무제한</li>
              <li>· 토스·테무·올웨이즈 자동 수집</li>
              <li>· 운송장 플랫폼 자동 등록(API)</li>
              <li>· 마진방어 무제한 + 적자 경고</li>
              <li>· 발주 이메일 자동 발송</li>
            </ul>
            <Link to="/signup" className="block text-center bg-emerald-600 text-white rounded-xl py-2.5 font-bold text-sm hover:bg-emerald-700">
              14일 무료체험 시작
            </Link>
          </div>
        </div>
      </section>

      {/* 푸터 */}
      <footer className="border-t border-gray-200 py-8 text-center text-xs text-gray-400">
        단하루 발주센터 · 위탁판매 발주 자동화 · <Link to="/pricing" className="underline">요금제</Link> · <Link to="/login" className="underline">로그인</Link>
      </footer>
    </div>
  );
}

export default LandingPage;
