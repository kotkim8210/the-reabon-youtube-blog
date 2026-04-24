import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { processTenantOrder, downloadBlob, getBillingMe, ProcessResult, BillingMe } from '../api';

function TenantOrderPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [billing, setBilling] = useState<BillingMe | null>(null);

  async function loadBilling() {
    try {
      setBilling(await getBillingMe());
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    loadBilling();
  }, []);

  const handleProcess = async () => {
    if (!file) {
      setError('DeliveryList 파일을 선택하세요.');
      return;
    }
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await processTenantOrder(file);
      setResult(res);
      downloadBlob(res.blob, res.filename);
      loadBilling();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '처리 중 오류가 발생했습니다.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const usage = billing?.usage.order_count ?? 0;
  const maxOrders = billing?.plan?.max_monthly_orders ?? null;
  const remaining = maxOrders !== null ? Math.max(0, maxOrders - usage) : null;
  const usedPct = maxOrders ? Math.min(100, (usage / maxOrders) * 100) : 0;
  const nearLimit = usedPct >= 90;
  const planCode = billing?.subscription.plan_code;

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">발주서 처리</h1>

      {billing && maxOrders !== null && (
        <div className={`mb-4 rounded-xl border p-4 ${nearLimit ? 'bg-amber-50 border-amber-200' : 'bg-indigo-50 border-indigo-100'}`}>
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-slate-700">
              이번달 남은 처리 건수{' '}
              <span className="font-bold">{remaining?.toLocaleString()}</span>
              <span className="text-slate-500"> / {maxOrders.toLocaleString()}건</span>
            </span>
            {planCode === 'free' && (
              <Link to="/pricing" className="text-indigo-600 hover:underline text-xs font-medium">
                Pro 업그레이드 →
              </Link>
            )}
          </div>
          <div className="mt-2 w-full bg-white/70 h-1.5 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all ${nearLimit ? 'bg-amber-500' : 'bg-indigo-500'}`}
              style={{ width: `${usedPct}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600">
          {error}
        </div>
      )}

      <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-6">
        <h3 className="text-sm font-bold text-gray-700 mb-4">DeliveryList 업로드</h3>
        <p className="text-xs text-gray-500 mb-4">
          쿠팡 DeliveryList 엑셀 파일을 업로드하면 설정된 상품별로 발주서가 자동 생성됩니다.
        </p>

        <div className="mb-4">
          <label className="block text-xs text-gray-500 mb-2">파일 선택</label>
          <input
            type="file"
            accept=".xlsx,.xls"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) setFile(f);
            }}
            className="w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4
                       file:rounded-lg file:border-0 file:text-sm file:font-medium
                       file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
          />
          {file && <p className="text-xs text-gray-400 mt-1">{file.name}</p>}
        </div>

        <button
          onClick={handleProcess}
          disabled={loading || !file}
          className="w-full py-3 bg-indigo-600 text-white rounded-xl font-semibold text-sm
                     hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed
                     transition-all flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              처리 중...
            </>
          ) : (
            '발주서 생성'
          )}
        </button>
      </div>

      {result && (
        <div className="bg-green-50 border border-green-200 rounded-2xl p-6 animate-fade-in">
          <h3 className="text-sm font-bold text-green-800 mb-2">처리 완료</h3>
          <p className="text-sm text-green-700 mb-3">{result.filename}</p>
          {result.stats && (
            <div className="text-xs text-green-600">
              {Object.entries(result.stats).map(([k, v]) => (
                <span key={k} className="mr-3">{k}: {String(v)}</span>
              ))}
            </div>
          )}
          <button
            onClick={() => downloadBlob(result.blob, result.filename)}
            className="mt-3 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700"
          >
            다시 다운로드
          </button>
        </div>
      )}
    </div>
  );
}

export default TenantOrderPage;
