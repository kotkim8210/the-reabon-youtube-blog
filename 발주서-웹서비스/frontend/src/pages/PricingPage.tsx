import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getPlans, getBillingConfig, subscribePro, Plan } from '../api';

declare global {
  interface Window { TossPayments?: any }
}

const TOSS_SDK_URL = 'https://js.tosspayments.com/v1/payment';

function loadTossScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.TossPayments) return resolve();
    const s = document.createElement('script');
    s.src = TOSS_SDK_URL;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('토스 SDK 로드 실패'));
    document.head.appendChild(s);
  });
}

export default function PricingPage() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [clientKey, setClientKey] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    getPlans().then((r) => setPlans(r.plans)).catch(() => {});
    getBillingConfig().then((r) => setClientKey(r.client_key)).catch(() => {});
  }, []);

  // Handle redirect back from Toss billing auth
  useEffect(() => {
    const url = new URL(window.location.href);
    const authKey = url.searchParams.get('authKey');
    const customerKey = url.searchParams.get('customerKey');
    if (authKey && customerKey) {
      setBusy(true);
      subscribePro(authKey, customerKey)
        .then(() => {
          alert('Pro 플랜 구독이 완료되었습니다.');
          navigate('/billing', { replace: true });
        })
        .catch((e) => setErr(e?.message || '결제 실패'))
        .finally(() => setBusy(false));
    }
  }, [navigate]);

  async function handleSubscribe() {
    if (!clientKey) {
      setErr('결제 설정이 아직 준비되지 않았습니다. 관리자에게 문의하세요.');
      return;
    }
    setErr(null);
    try {
      await loadTossScript();
      const token = localStorage.getItem('token');
      if (!token) {
        navigate('/login');
        return;
      }
      const customerKey = `balju-${Date.now()}`;
      const tp = window.TossPayments(clientKey);
      await tp.requestBillingAuth('카드', {
        customerKey,
        successUrl: window.location.origin + '/pricing',
        failUrl: window.location.origin + '/pricing?status=fail',
      });
    } catch (e: any) {
      setErr(e?.message || '결제 창 호출 실패');
    }
  }

  const freePlan = plans.find((p) => p.code === 'free');
  const proPlan = plans.find((p) => p.code === 'pro');

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="max-w-4xl mx-auto">
        <header className="text-center mb-10 mt-8">
          <h1 className="text-3xl font-bold text-slate-900">요금제</h1>
          <p className="text-slate-500 mt-2">무료로 시작하고 필요할 때 업그레이드하세요.</p>
        </header>

        {err && (
          <div className="mb-4 bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-lg">
            {err}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl p-8 shadow-sm">
            <h2 className="text-xl font-semibold">{freePlan?.name || '무료'}</h2>
            <p className="text-3xl font-bold mt-3">₩0 <span className="text-sm text-slate-500 font-normal">/월</span></p>
            <ul className="mt-6 space-y-2 text-sm text-slate-700">
              <li>✔ 제품 {freePlan?.max_products ?? 1}개 등록</li>
              <li>✔ 월 {freePlan?.max_monthly_orders ?? 50}건 처리</li>
              <li>✔ 판매 대시보드 (최근 30일)</li>
              <li className="text-slate-400">✘ 운송장 자동 입력</li>
              <li className="text-slate-400">✘ 쿠팡 실시간 재고/가격</li>
            </ul>
            <Link
              to="/signup"
              className="mt-8 block text-center border border-slate-300 hover:border-slate-400 text-slate-700 font-medium py-2.5 rounded-lg"
            >
              무료로 시작하기
            </Link>
          </div>

          <div className="bg-white rounded-xl p-8 shadow-lg border-2 border-indigo-500 relative">
            <span className="absolute -top-3 left-6 bg-indigo-600 text-white text-xs font-semibold px-3 py-1 rounded-full">추천</span>
            <h2 className="text-xl font-semibold">{proPlan?.name || 'Pro'}</h2>
            <p className="text-3xl font-bold mt-3">
              ₩{(proPlan?.price_krw ?? 29000).toLocaleString()} <span className="text-sm text-slate-500 font-normal">/월</span>
            </p>
            <ul className="mt-6 space-y-2 text-sm text-slate-700">
              <li>✔ 제품 무제한 등록</li>
              <li>✔ 월 {proPlan?.max_monthly_orders?.toLocaleString() ?? '3,000'}건 처리</li>
              <li>✔ 판매 대시보드 (전체 기간)</li>
              <li>✔ 운송장 자동 입력</li>
              <li>✔ 쿠팡 실시간 재고/가격</li>
              <li>✔ 자동 가격 조정</li>
            </ul>
            <button
              onClick={handleSubscribe}
              disabled={busy}
              className="mt-8 w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2.5 rounded-lg"
            >
              {busy ? '처리 중…' : 'Pro 구독하기'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
