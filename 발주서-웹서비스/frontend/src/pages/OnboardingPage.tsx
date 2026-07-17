import { Link } from 'react-router-dom';

const STEPS = [
  {
    no: 1,
    icon: '🏭',
    title: '내 상품과 발주서 양식 등록',
    desc: '판매 중인 상품과 거래처(산지) 발주서 양식을 등록하세요. 회신 파일 예시를 올리면 열 구조를 자동 인식합니다.',
    cta: '상품/양식 설정하기',
    to: '/my/products',
    time: '약 2분',
  },
  {
    no: 2,
    icon: '📦',
    title: '첫 발주서 만들기',
    desc: '쿠팡 DeliveryList를 업로드하면 등록한 양식으로 발주서가 생성됩니다. 다운로드해서 거래처에 그대로 전달하면 끝.',
    cta: '첫 발주서 생성하기',
    to: '/my/process',
    time: '약 1분',
  },
  {
    no: 3,
    icon: '🚀',
    title: 'Pro 체험 기능 둘러보기',
    desc: '지금 14일 Pro 체험 중입니다 — 토스·테무 자동 수집, 운송장 자동 등록, 마진방어까지 전부 열려 있어요. 체험이 끝나면 자동으로 Free 플랜이 됩니다(자동결제 없음).',
    cta: '구독 & 사용량 보기',
    to: '/billing',
    time: '',
  },
];

function OnboardingPage() {
  return (
    <div className="max-w-2xl mx-auto">
      <div className="text-center mb-8">
        <p className="text-4xl mb-3">🎉</p>
        <h1 className="text-2xl font-extrabold text-gray-900 mb-2">가입 완료! 3분이면 첫 발주서가 나옵니다</h1>
        <p className="text-sm text-gray-500">
          <b className="text-emerald-700">14일 Pro 무료체험</b>이 시작됐어요 (카드 등록 없음 · 종료 시 자동으로 Free 전환).
          아래 순서대로 진행해 보세요.
        </p>
      </div>

      <div className="space-y-4">
        {STEPS.map((s) => (
          <div key={s.no} className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 flex items-start gap-4">
            <div className="w-9 h-9 rounded-full bg-emerald-600 text-white font-extrabold flex items-center justify-center flex-none">
              {s.no}
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xl">{s.icon}</span>
                <h2 className="font-bold text-gray-900">{s.title}</h2>
                {s.time && <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">{s.time}</span>}
              </div>
              <p className="text-sm text-gray-500 mb-3 leading-relaxed">{s.desc}</p>
              <Link
                to={s.to}
                className="inline-block bg-emerald-600 text-white px-4 py-2 rounded-xl font-semibold text-sm hover:bg-emerald-700 transition-all"
              >
                {s.cta} →
              </Link>
            </div>
          </div>
        ))}
      </div>

      <p className="text-center text-xs text-gray-400 mt-8">
        언제든 왼쪽 메뉴에서 같은 화면으로 이동할 수 있어요 · 막히면 <Link to="/billing" className="underline">구독 & 사용량</Link>에서 상태를 확인하세요
      </p>
    </div>
  );
}

export default OnboardingPage;
