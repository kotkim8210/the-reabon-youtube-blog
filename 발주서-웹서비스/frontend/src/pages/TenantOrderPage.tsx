import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { processTenantOrder, processTenantTracking, downloadBlob, getBillingMe, ProcessResult, BillingMe } from '../api';

function TenantOrderPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [trackingLoading, setTrackingLoading] = useState(false);
  const [trackingError, setTrackingError] = useState('');
  const [trackingResult, setTrackingResult] = useState<ProcessResult | null>(null);
  const [replyFiles, setReplyFiles] = useState<File[]>([]);
  const [trackingDeliveryFile, setTrackingDeliveryFile] = useState<File | null>(null);
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

  const handleTracking = async () => {
    if (!replyFiles.length) {
      setTrackingError('회신/송장 파일을 1개 이상 선택하세요.');
      return;
    }
    if (!trackingDeliveryFile) {
      setTrackingError('송장번호를 채울 원본 DeliveryList 파일을 선택하세요.');
      return;
    }
    setTrackingLoading(true);
    setTrackingError('');
    setTrackingResult(null);
    try {
      const res = await processTenantTracking(replyFiles, trackingDeliveryFile);
      setTrackingResult(res);
      downloadBlob(res.blob, res.filename);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '송장번호 입력 중 오류가 발생했습니다.';
      setTrackingError(msg);
    } finally {
      setTrackingLoading(false);
    }
  };

  const addReplyFiles = (files: FileList | null) => {
    if (!files) return;
    const currentKeys = new Set(replyFiles.map((f) => `${f.name}:${f.size}:${f.lastModified}`));
    const next = [...replyFiles];
    Array.from(files).forEach((f) => {
      const key = `${f.name}:${f.size}:${f.lastModified}`;
      if (!currentKeys.has(key)) {
        currentKeys.add(key);
        next.push(f);
      }
    });
    setReplyFiles(next);
  };

  const usage = billing?.usage.order_count ?? 0;
  const maxOrders = billing?.plan?.max_monthly_orders ?? null;
  const remaining = maxOrders !== null ? Math.max(0, maxOrders - usage) : null;
  const usedPct = maxOrders ? Math.min(100, (usage / maxOrders) * 100) : 0;
  const nearLimit = usedPct >= 90;
  const planCode = billing?.subscription.plan_code;

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-600">My Automation</p>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">내 발주/송장 자동화</h1>
        <p className="mt-2 text-sm leading-6 text-gray-500">
          상품/양식 설정에 등록한 규칙으로 발주서를 만들고, 거래처 회신 파일의 송장번호를 원본 DeliveryList에 다시 입력합니다.
        </p>
      </div>

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

      {trackingError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600">
          {trackingError}
        </div>
      )}

      <div className="mb-4 rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-bold text-slate-800">처음 쓰는 계정인가요?</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              먼저 거래처 엑셀 양식과 상품/옵션 매칭을 등록해야 이 화면에서 발주서가 생성됩니다.
            </p>
          </div>
          <Link
            to="/my/products"
            className="inline-flex items-center justify-center rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2 text-xs font-bold text-indigo-700 transition hover:bg-indigo-100"
          >
            상품/양식 설정
          </Link>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-gray-200 p-6 mb-6">
        <h3 className="text-sm font-bold text-gray-700 mb-4">DeliveryList 업로드</h3>
        <p className="text-xs text-gray-500 mb-4">
          쿠팡 DeliveryList 엑셀 파일을 업로드하면 설정된 상품별로 발주서가 자동 생성됩니다.
          여러 상품이 매칭되면 ZIP 파일로 한 번에 내려받습니다.
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

      <div className="bg-slate-950 rounded-2xl border border-slate-800 p-6 mt-6 mb-6 text-white">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-sky-300">Tracking Input</p>
        <h3 className="mt-2 text-xl font-black">송장번호 입력</h3>
        <p className="mt-2 text-xs leading-5 text-slate-300">
          거래처 회신/송장 파일을 여러 개 추가하고, 송장번호를 채울 원본 DeliveryList를 올리면 최종 송장입력완료 파일을 내려받습니다.
          헤더에 송장번호·수취인·연락처·주소·택배사가 있으면 자동으로 열을 찾아 처리합니다.
        </p>

        <div className="mt-5 space-y-4">
          <div className="rounded-2xl border border-dashed border-white/15 bg-white/5 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-semibold text-white">회신/송장 파일</p>
                <p className="text-xs text-slate-400">여러 파일을 한 번에 선택하거나 여러 번 추가할 수 있습니다.</p>
              </div>
              <label className="inline-flex cursor-pointer items-center justify-center rounded-full bg-white px-4 py-2 text-sm font-bold text-slate-900 transition hover:bg-sky-50">
                파일 추가
                <input
                  type="file"
                  accept=".xlsx,.xls"
                  multiple
                  className="hidden"
                  onChange={(event) => {
                    addReplyFiles(event.target.files);
                    event.target.value = '';
                  }}
                />
              </label>
            </div>
            {replyFiles.length > 0 && (
              <div className="mt-3 space-y-2">
                {replyFiles.map((reply, index) => (
                  <div key={`${reply.name}-${reply.lastModified}`} className="flex items-center gap-2 rounded-xl bg-white/10 px-3 py-2 text-xs text-slate-100">
                    <span className="min-w-0 flex-1 truncate">{reply.name}</span>
                    <button
                      type="button"
                      onClick={() => setReplyFiles(replyFiles.filter((_, i) => i !== index))}
                      className="rounded-full bg-white/10 px-2 py-1 text-[11px] text-slate-300 hover:bg-rose-500/20 hover:text-rose-100"
                    >
                      삭제
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
            <p className="text-sm font-semibold text-white">DeliveryList 원본</p>
            <p className="mt-1 text-xs text-slate-400">송장번호를 입력할 쿠팡 DeliveryList 파일입니다.</p>
            <label className="mt-3 inline-flex cursor-pointer items-center justify-center rounded-full bg-white px-4 py-2 text-sm font-bold text-slate-900 transition hover:bg-emerald-50">
              파일 선택
              <input
                type="file"
                accept=".xlsx,.xls"
                className="hidden"
                onChange={(event) => {
                  const f = event.target.files?.[0];
                  if (f) setTrackingDeliveryFile(f);
                }}
              />
            </label>
            {trackingDeliveryFile && <p className="mt-2 text-xs text-slate-300">{trackingDeliveryFile.name}</p>}
          </div>

          <button
            onClick={handleTracking}
            disabled={trackingLoading || !replyFiles.length || !trackingDeliveryFile}
            className="w-full rounded-xl bg-sky-400 py-3 text-sm font-black text-slate-950 transition hover:bg-sky-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {trackingLoading ? '송장번호 입력 중...' : 'DeliveryList에 송장번호 입력'}
          </button>
        </div>
      </div>

      {trackingResult && (
        <div className="bg-green-50 border border-green-200 rounded-2xl p-6 animate-fade-in">
          <h3 className="text-sm font-bold text-green-800 mb-2">송장 입력 완료</h3>
          <p className="text-sm text-green-700 mb-3">{trackingResult.filename}</p>
          {trackingResult.stats && (
            <div className="text-xs text-green-600">
              {Object.entries(trackingResult.stats).map(([k, v]) => (
                <span key={k} className="mr-3">{k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
              ))}
            </div>
          )}
          <button
            onClick={() => downloadBlob(trackingResult.blob, trackingResult.filename)}
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
