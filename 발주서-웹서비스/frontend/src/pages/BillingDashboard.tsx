import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getBillingMe, cancelSubscription, resumeSubscription, BillingMe } from '../api';

export default function BillingDashboard() {
  const [data, setData] = useState<BillingMe | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setData(await getBillingMe());
    } catch (e: any) {
      setErr(e?.message || '불러오기 실패');
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCancel() {
    if (!confirm('기간 만료 후 해지됩니다. 진행하시겠어요?')) return;
    setBusy(true);
    try {
      await cancelSubscription();
      await load();
    } catch (e: any) {
      setErr(e?.message || '해지 실패');
    } finally {
      setBusy(false);
    }
  }

  async function handleResume() {
    setBusy(true);
    try {
      await resumeSubscription();
      await load();
    } catch (e: any) {
      setErr(e?.message || '재개 실패');
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <div className="p-6 text-slate-500">불러오는 중…</div>;

  const { subscription: sub, plan, usage } = data;
  const maxOrders = plan?.max_monthly_orders ?? null;
  const usedPct = maxOrders ? Math.min(100, (usage.order_count / maxOrders) * 100) : 0;
  const isPro = sub.plan_code === 'pro';

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">구독 & 사용량</h1>
        <p className="text-slate-500 text-sm mt-1">{usage.ym} 월 기준</p>
      </header>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-2 rounded-lg">{err}</div>}

      <section className="bg-white rounded-xl shadow-sm p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-slate-500">현재 플랜</p>
            <p className="text-2xl font-semibold">{plan?.name || sub.plan_code}</p>
            {sub.current_period_end && (
              <p className="text-xs text-slate-500 mt-1">
                다음 결제: {new Date(sub.current_period_end).toLocaleDateString('ko-KR')}
              </p>
            )}
            {sub.cancel_at_period_end && (
              <p className="text-xs text-amber-700 mt-1">기간 만료 후 해지 예정</p>
            )}
          </div>
          <div>
            {!isPro ? (
              <Link to="/pricing" className="bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-4 py-2 rounded-lg">
                Pro 업그레이드
              </Link>
            ) : sub.cancel_at_period_end ? (
              <button onClick={handleResume} disabled={busy} className="border border-indigo-600 text-indigo-600 hover:bg-indigo-50 font-medium px-4 py-2 rounded-lg">
                구독 재개
              </button>
            ) : (
              <button onClick={handleCancel} disabled={busy} className="text-slate-500 hover:text-rose-600 text-sm">
                구독 해지
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="bg-white rounded-xl shadow-sm p-6">
        <p className="text-sm font-medium text-slate-700 mb-3">이번달 처리 건수</p>
        <div className="flex items-baseline gap-2 mb-3">
          <span className="text-3xl font-bold">{usage.order_count.toLocaleString()}</span>
          <span className="text-slate-500">
            {maxOrders ? `/ ${maxOrders.toLocaleString()}건` : '(무제한)'}
          </span>
        </div>
        {maxOrders && (
          <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${usedPct > 90 ? 'bg-rose-500' : usedPct > 70 ? 'bg-amber-500' : 'bg-indigo-500'}`}
              style={{ width: `${usedPct}%` }}
            />
          </div>
        )}
      </section>
    </div>
  );
}
