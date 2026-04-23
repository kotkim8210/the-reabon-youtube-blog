import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { SlidersHorizontal, Lock, Layers } from 'lucide-react';
import ProcessCard from '../components/ProcessCard';
import { useUser } from '../App';
import { getBillingMe } from '../api';
import { getVisibleTools } from '../lib/toolCatalog';

function OrderTools() {
  const navigate = useNavigate();
  const { user } = useUser();
  const userId = user?.user_id ?? 'anon';
  const isAdmin = user?.role === 'admin';
  const [planCode, setPlanCode] = useState<string>('free');
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    getBillingMe()
      .then((r) => setPlanCode(r.subscription.plan_code))
      .catch(() => setPlanCode('free'))
      .finally(() => setChecking(false));
  }, []);

  const allowed = isAdmin || planCode === 'pro';
  const tools = getVisibleTools(userId);

  if (checking) {
    return <div className="text-slate-500 text-sm">불러오는 중…</div>;
  }

  if (!allowed) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="bg-white rounded-2xl border border-slate-200 p-8 text-center shadow-sm">
          <Lock size={32} className="mx-auto text-slate-400 mb-3" />
          <h2 className="text-xl font-bold text-slate-900">Pro 전용 도구</h2>
          <p className="text-sm text-slate-500 mt-2">
            산지직송 발주서/운송장 자동화 도구는 Pro 플랜에서 사용할 수 있습니다.<br />
            무료 플랜에서는 "발주서 처리" 메뉴의 범용 엔진을 이용해 주세요.
          </p>
          <div className="mt-6 flex justify-center gap-2">
            <Link
              to="/pricing"
              className="bg-indigo-600 hover:bg-indigo-700 text-white font-medium px-4 py-2 rounded-lg"
            >
              Pro 업그레이드
            </Link>
            <Link
              to="/my/process"
              className="border border-slate-300 hover:border-slate-400 text-slate-700 font-medium px-4 py-2 rounded-lg"
            >
              발주서 처리로 이동
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800">발주서 & 운송장 도구</h2>
          <p className="text-slate-500 mt-1">사용할 도구를 선택해주세요</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/orders/settings')}
            className="flex items-center gap-1 text-xs text-slate-600 hover:bg-slate-100 border border-slate-200 rounded-lg px-3 py-2"
          >
            <SlidersHorizontal size={14} /> 도구 설정
          </button>
        </div>
      </div>

      {/* 일괄 운송장 입력 배너 */}
      <button
        onClick={() => navigate('/orders/batch-tracking')}
        className="w-full mb-5 flex items-center gap-3 bg-indigo-600 hover:bg-indigo-700
          text-white rounded-xl px-5 py-4 shadow-md shadow-indigo-200 transition-colors text-left"
      >
        <div className="w-9 h-9 bg-white/20 rounded-lg flex items-center justify-center shrink-0">
          <Layers size={18} />
        </div>
        <div>
          <p className="font-semibold text-sm">일괄 운송장 입력</p>
          <p className="text-xs text-indigo-200">여러 거래처 파일을 한 번에 올려서 처리 (고구마 제외)</p>
        </div>
        <svg className="ml-auto w-4 h-4 text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      {tools.length === 0 ? (
        <div className="bg-white rounded-2xl border border-dashed border-slate-200 p-10 text-center text-slate-400 text-sm">
          표시할 도구가 없습니다.{' '}
          <Link to="/orders/settings" className="text-indigo-600 hover:underline">
            도구 설정
          </Link>
          에서 숨김/삭제한 항목을 복원할 수 있습니다.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {tools.map((tool) => (
            <ProcessCard
              key={tool.id}
              title={tool.title}
              description={tool.description}
              icon={tool.icon}
              color={tool.color}
              onClick={() => {
                if (tool.id === 'goguma-unified') {
                  navigate('/process/goguma');
                } else if (tool.id.endsWith('-unified')) {
                  const productId = tool.id.replace('-unified', '');
                  navigate(`/process/unified/${productId}`);
                } else {
                  navigate(`/process/${tool.id}`);
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default OrderTools;
