import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  processGogumaAuto, processGogumaTrackingApi,
  processTossOrder, processTossTrackingApi,
  processFile,
  downloadBlob, ProcessResult, TrackingApiResult,
  fetchTossOrders, fetchTossClaims, testTossConnection,
  approveTossCancel, rejectTossCancel,
  approveTossExchange, rejectTossExchange,
  approveTossReturn, rejectTossReturn,
  TossOrder, TossClaim,
} from '../api';
import FileUpload from '../components/FileUpload';

function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

// ── Shared UI Components ────────────────────────────────────────
function Spinner({ text, color = 'blue' }: { text: string; color?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center animate-fade-in">
      <svg className={`animate-spin w-10 h-10 text-${color}-500 mx-auto mb-4`} fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <p className="text-sm font-semibold text-gray-900">{text}</p>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-2xl p-5 mb-4 animate-fade-in">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 bg-red-100 rounded-xl flex items-center justify-center flex-shrink-0">
          <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.07 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
        </div>
        <div>
          <h4 className="text-sm font-bold text-red-800 mb-0.5">오류 발생</h4>
          <p className="text-sm text-red-600">{message}</p>
        </div>
      </div>
    </div>
  );
}

function PlatformBadge({ platform }: { platform: 'coupang' | 'toss' | 'alwayz' }) {
  const config = platform === 'coupang'
    ? { label: '쿠팡', bg: 'bg-orange-100', text: 'text-orange-700', dot: 'bg-orange-500' }
    : platform === 'alwayz'
    ? { label: '올웨이즈', bg: 'bg-purple-100', text: 'text-purple-700', dot: 'bg-purple-500' }
    : { label: '토스', bg: 'bg-blue-100', text: 'text-blue-700', dot: 'bg-blue-500' };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${config.bg} ${config.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {config.label}
    </span>
  );
}

// ── Tracking Result Display ─────────────────────────────────────
function TrackingResultView({ result, platform }: { result: TrackingApiResult; platform: string }) {
  return (
    <div className="animate-fade-in space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <h4 className="text-sm font-bold text-gray-700">{platform} 운송장 등록 결과</h4>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-green-700">{result.success}</p>
          <p className="text-xs font-semibold text-green-600 mt-1">성공</p>
        </div>
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-red-700">{result.fail}</p>
          <p className="text-xs font-semibold text-red-600 mt-1">실패</p>
        </div>
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
          <p className="text-2xl font-bold text-gray-700">{result.skip}</p>
          <p className="text-xs font-semibold text-gray-600 mt-1">스킵</p>
        </div>
      </div>
      {result.results.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="max-h-60 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">수령인</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">운송장번호</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">상태</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">메시지</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {result.results.map((r, i) => (
                  <tr key={i} className={
                    r.status === 'success' ? 'bg-green-50/50' :
                    r.status === 'fail' ? 'bg-red-50/50' : ''
                  }>
                    <td className="px-4 py-2 font-medium text-gray-900">{r.name}</td>
                    <td className="px-4 py-2 text-gray-600 font-mono text-xs">{r.tracking || '-'}</td>
                    <td className="px-4 py-2">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-semibold ${
                        r.status === 'success' ? 'bg-green-100 text-green-700' :
                        r.status === 'fail' ? 'bg-red-100 text-red-700' :
                        'bg-gray-100 text-gray-600'
                      }`}>{r.status === 'success' ? '성공' : r.status === 'fail' ? '실패' : '스킵'}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500">{r.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// TAB 1: 발주서 생성 (쿠팡 + 토스 병렬)
// ══════════════════════════════════════════════════════════════════
function OrderCollectionTab() {
  const today = new Date();
  // Shared date range
  const [fromDate, setFromDate] = useState(formatDate(today));
  const [toDate, setToDate] = useState(formatDate(today));

  // Coupang state
  const [coupangLoading, setCoupangLoading] = useState(false);
  const [coupangResult, setCoupangResult] = useState<ProcessResult | null>(null);
  const [coupangError, setCoupangError] = useState('');

  // Toss state
  const [tossLoading, setTossLoading] = useState(false);
  const [tossResult, setTossResult] = useState<ProcessResult | null>(null);
  const [tossError, setTossError] = useState('');
  const [tossOrders, setTossOrders] = useState<TossOrder[]>([]);
  const [tossOrderStatus, setTossOrderStatus] = useState('');
  const [tossQueryLoading, setTossQueryLoading] = useState(false);
  const [tossTotal, setTossTotal] = useState(0);

  const setDateRange = useCallback((days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setFromDate(formatDate(start));
    setToDate(formatDate(end));
    setCoupangResult(null);
    setCoupangError('');
    setTossResult(null);
    setTossError('');
  }, []);

  const getActiveDays = (): number | null => {
    const end = new Date(toDate);
    const start = new Date(fromDate);
    const diff = Math.round((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;
    if (toDate === formatDate(today) && diff >= 1 && diff <= 4) return diff;
    return null;
  };
  const activeDays = getActiveDays();

  const quickButtons = [
    { days: 1, label: '오늘', sub: '' },
    { days: 2, label: '2일', sub: '' },
    { days: 3, label: '3일', sub: '공휴일 다음날' },
    { days: 4, label: '4일', sub: '주말직후 월요일' },
  ];

  // Collect from both platforms simultaneously
  const handleCollectAll = async () => {
    setCoupangLoading(true);
    setTossLoading(true);
    setCoupangError('');
    setTossError('');
    setCoupangResult(null);
    setTossResult(null);

    const coupangPromise = processGogumaAuto(fromDate, toDate)
      .then((res) => setCoupangResult(res))
      .catch((err) => setCoupangError(err instanceof Error ? err.message : '쿠팡 처리 중 오류'))
      .finally(() => setCoupangLoading(false));

    const tossPromise = processTossOrder(fromDate, toDate)
      .then((res) => setTossResult(res))
      .catch((err) => setTossError(err instanceof Error ? err.message : '토스 처리 중 오류'))
      .finally(() => setTossLoading(false));

    await Promise.allSettled([coupangPromise, tossPromise]);
  };

  const handleCollectCoupang = async () => {
    setCoupangLoading(true);
    setCoupangError('');
    setCoupangResult(null);
    try {
      const res = await processGogumaAuto(fromDate, toDate);
      setCoupangResult(res);
    } catch (err) {
      setCoupangError(err instanceof Error ? err.message : '쿠팡 처리 중 오류');
    } finally {
      setCoupangLoading(false);
    }
  };

  const handleCollectToss = async () => {
    setTossLoading(true);
    setTossError('');
    setTossResult(null);
    try {
      const res = await processTossOrder(fromDate, toDate);
      setTossResult(res);
    } catch (err) {
      setTossError(err instanceof Error ? err.message : '토스 처리 중 오류');
    } finally {
      setTossLoading(false);
    }
  };

  const handleTossQuery = async () => {
    setTossQueryLoading(true);
    setTossError('');
    try {
      const res = await fetchTossOrders(fromDate, toDate, tossOrderStatus || undefined);
      setTossOrders(res.orders);
      setTossTotal(res.total);
    } catch (err) {
      setTossError(err instanceof Error ? err.message : '토스 주문 조회 실패');
    } finally {
      setTossQueryLoading(false);
    }
  };

  const ORDER_STATUSES = [
    { value: '', label: '전체' },
    { value: 'PAID', label: '결제완료' },
    { value: 'PREPARING_PRODUCT', label: '상품준비중' },
    { value: 'DELIVERING', label: '배송중' },
    { value: 'DELIVERED', label: '배송완료' },
  ];

  const anyLoading = coupangLoading || tossLoading;

  return (
    <div className="space-y-6">
      {/* Shared Date Selection */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-base font-bold text-gray-900 mb-4">기간 선택</h3>
        <div className="flex gap-2 mb-5">
          {quickButtons.map(({ days, label, sub }) => (
            <button key={days} onClick={() => setDateRange(days)}
              className={`px-5 py-2.5 rounded-xl font-semibold text-sm transition-all duration-200 text-center ${
                activeDays === days
                  ? 'bg-orange-500 text-white shadow-md shadow-orange-200'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {label}
              {sub && (
                <span className={`block text-[10px] font-medium mt-0.5 ${
                  activeDays === days ? 'text-orange-100' : 'text-gray-400'
                }`}>{sub}</span>
              )}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1.5">시작일</label>
            <input type="date" value={fromDate}
              onChange={(e) => { setFromDate(e.target.value); setCoupangResult(null); setTossResult(null); }}
              max={toDate}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-orange-300 focus:border-orange-400 outline-none transition-all" />
          </div>
          <div className="pt-5 text-gray-400 font-medium">~</div>
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1.5">종료일</label>
            <input type="date" value={toDate}
              onChange={(e) => { setToDate(e.target.value); setCoupangResult(null); setTossResult(null); }}
              min={fromDate} max={formatDate(today)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-orange-300 focus:border-orange-400 outline-none transition-all" />
          </div>
        </div>
        <div className="px-4 py-2.5 bg-orange-50 rounded-xl mb-5">
          <p className="text-sm text-orange-700">
            <span className="font-semibold">수집 기간:</span> {fromDate} ~ {toDate}
            {fromDate === toDate && ' (당일)'}
          </p>
        </div>

        {/* Collect buttons */}
        <div className="flex items-center gap-3">
          <button onClick={handleCollectAll} disabled={anyLoading}
            className="bg-gradient-to-r from-orange-500 to-blue-500 text-white px-6 py-3 rounded-xl font-semibold text-sm
                       hover:from-orange-600 hover:to-blue-600
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all duration-200 flex items-center gap-2 shadow-lg">
            {anyLoading ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                수집 중...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                전체 수집 (쿠팡 + 토스)
              </>
            )}
          </button>
          <button onClick={handleCollectCoupang} disabled={anyLoading}
            className="bg-orange-500 text-white px-5 py-3 rounded-xl font-semibold text-sm hover:bg-orange-600 disabled:opacity-50 transition-all shadow-md shadow-orange-200">
            {coupangLoading ? '수집 중...' : '쿠팡만'}
          </button>
          <button onClick={handleCollectToss} disabled={anyLoading}
            className="bg-blue-500 text-white px-5 py-3 rounded-xl font-semibold text-sm hover:bg-blue-600 disabled:opacity-50 transition-all shadow-md shadow-blue-200">
            {tossLoading ? '수집 중...' : '토스만'}
          </button>
        </div>
      </div>

      {/* Results - Two columns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Coupang Result */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-4">
            <PlatformBadge platform="coupang" />
            <span className="text-sm font-bold text-gray-900">발주서</span>
          </div>
          {coupangLoading && <Spinner text="쿠팡 API에서 결제완료 주문을 수집 중..." color="orange" />}
          {coupangError && <ErrorBanner message={coupangError} />}
          {coupangResult && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 animate-fade-in">
              <h4 className="text-sm font-bold text-green-800 mb-1">수집 완료</h4>
              {coupangResult.stats && (
                <div className="space-y-0.5 mb-3">
                  {Object.entries(coupangResult.stats).map(([key, value]) => (
                    <p key={key} className="text-sm text-green-700">
                      {key === 'total' ? `수집된 주문: ${value}건` :
                       key === 'period' ? `수집 기간: ${value}` :
                       `${key}: ${value}`}
                    </p>
                  ))}
                </div>
              )}
              <button onClick={() => downloadBlob(coupangResult.blob, coupangResult.filename)}
                className="inline-flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-xl font-semibold text-sm hover:bg-green-700 transition-all shadow-sm">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {coupangResult.filename}
              </button>
            </div>
          )}
          {!coupangLoading && !coupangResult && !coupangError && (
            <p className="text-sm text-gray-400 text-center py-8">기간을 선택하고 수집 버튼을 클릭하세요</p>
          )}
        </div>

        {/* Toss Result */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-4">
            <PlatformBadge platform="toss" />
            <span className="text-sm font-bold text-gray-900">발주서</span>
          </div>
          {tossLoading && <Spinner text="토스 API에서 주문을 수집 중..." />}
          {tossError && <ErrorBanner message={tossError} />}
          {tossResult && (
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 animate-fade-in">
              <h4 className="text-sm font-bold text-green-800 mb-1">수집 완료</h4>
              {tossResult.stats && Object.entries(tossResult.stats).map(([k, v]) => (
                <p key={k} className="text-sm text-green-700">{k}: {String(v)}</p>
              ))}
              <button onClick={() => downloadBlob(tossResult.blob, tossResult.filename)}
                className="mt-3 inline-flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-xl font-semibold text-sm hover:bg-green-700 transition-all shadow-sm">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {tossResult.filename}
              </button>
            </div>
          )}
          {!tossLoading && !tossResult && !tossError && (
            <p className="text-sm text-gray-400 text-center py-8">기간을 선택하고 수집 버튼을 클릭하세요</p>
          )}
        </div>
      </div>

      {/* Toss Order Query (optional detail view) */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-5">
        <div className="flex items-center gap-2 mb-4">
          <PlatformBadge platform="toss" />
          <span className="text-sm font-bold text-gray-900">주문 상세 조회</span>
        </div>
        <div className="flex items-center gap-3 mb-4">
          <select value={tossOrderStatus} onChange={(e) => setTossOrderStatus(e.target.value)}
            className="px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-blue-300 outline-none">
            {ORDER_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
          <button onClick={handleTossQuery} disabled={tossQueryLoading}
            className="bg-blue-500 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-blue-600 disabled:opacity-50 transition-all shadow-md shadow-blue-200">
            {tossQueryLoading ? '조회 중...' : '주문 조회'}
          </button>
        </div>
        {tossQueryLoading && <Spinner text="토스 주문을 조회하고 있습니다..." />}
        {!tossQueryLoading && tossOrders.length > 0 && (
          <div className="border border-gray-200 rounded-xl overflow-hidden">
            <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
              <p className="text-sm font-semibold text-gray-700">총 {tossTotal}건</p>
            </div>
            <div className="max-h-[400px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">주문번호</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">상품명</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">옵션</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">수량</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">수취인</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">상태</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {tossOrders.map((o, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="px-4 py-2 text-gray-700 font-mono text-xs">{o.orderId || o.orderNumber || '-'}</td>
                      <td className="px-4 py-2 text-gray-900">{o.productName || '-'}</td>
                      <td className="px-4 py-2 text-gray-600 text-xs">{o.optionName || '-'}</td>
                      <td className="px-4 py-2 text-gray-700">{o.quantity || 1}</td>
                      <td className="px-4 py-2 text-gray-700">{o.receiverName || '-'}</td>
                      <td className="px-4 py-2">
                        <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-700">
                          {o.status || '-'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// TAB 2: 운송장 등록 (쿠팡 + 토스 병렬)
// ══════════════════════════════════════════════════════════════════
function TrackingTab() {
  // Coupang tracking
  const [coupangFile, setCoupangFile] = useState<File | null>(null);
  const [coupangLoading, setCoupangLoading] = useState(false);
  const [coupangResult, setCoupangResult] = useState<TrackingApiResult | null>(null);
  const [coupangError, setCoupangError] = useState('');

  // Toss tracking
  const [tossFile, setTossFile] = useState<File | null>(null);
  const [tossLoading, setTossLoading] = useState(false);
  const [tossResult, setTossResult] = useState<TrackingApiResult | null>(null);
  const [tossError, setTossError] = useState('');

  // Alwayz tracking (file-based)
  const [alwayzHaedalFile, setAlwayzHaedalFile] = useState<File | null>(null);
  const [alwayzOrderFile, setAlwayzOrderFile] = useState<File | null>(null);
  const [alwayzLoading, setAlwayzLoading] = useState(false);
  const [alwayzStats, setAlwayzStats] = useState<Record<string, unknown> | null>(null);
  const [alwayzError, setAlwayzError] = useState('');

  const handleCoupangUpload = async () => {
    if (!coupangFile) return;
    setCoupangLoading(true);
    setCoupangError('');
    setCoupangResult(null);
    try {
      const res = await processGogumaTrackingApi(coupangFile);
      setCoupangResult(res);
    } catch (err) {
      setCoupangError(err instanceof Error ? err.message : '처리 중 오류');
    } finally {
      setCoupangLoading(false);
    }
  };

  const handleTossUpload = async () => {
    if (!tossFile) return;
    setTossLoading(true);
    setTossError('');
    setTossResult(null);
    try {
      const res = await processTossTrackingApi(tossFile);
      setTossResult(res);
    } catch (err) {
      setTossError(err instanceof Error ? err.message : '처리 중 오류');
    } finally {
      setTossLoading(false);
    }
  };

  const handleBothUpload = async () => {
    const promises: Promise<void>[] = [];
    if (coupangFile) {
      setCoupangLoading(true);
      setCoupangError('');
      setCoupangResult(null);
      promises.push(
        processGogumaTrackingApi(coupangFile)
          .then((res) => setCoupangResult(res))
          .catch((err) => setCoupangError(err instanceof Error ? err.message : '쿠팡 처리 중 오류'))
          .finally(() => setCoupangLoading(false))
      );
    }
    if (tossFile) {
      setTossLoading(true);
      setTossError('');
      setTossResult(null);
      promises.push(
        processTossTrackingApi(tossFile)
          .then((res) => setTossResult(res))
          .catch((err) => setTossError(err instanceof Error ? err.message : '토스 처리 중 오류'))
          .finally(() => setTossLoading(false))
      );
    }
    await Promise.allSettled(promises);
  };

  const handleAlwayzUpload = async () => {
    if (!alwayzHaedalFile || !alwayzOrderFile) return;
    setAlwayzLoading(true);
    setAlwayzError('');
    setAlwayzStats(null);
    try {
      const result = await processFile('goguma-tracking-alwayz', {
        haedal: alwayzHaedalFile,
        alwayz: alwayzOrderFile,
      });
      setAlwayzStats(result.stats);
      downloadBlob(result.blob, result.filename);
    } catch (err) {
      setAlwayzError(err instanceof Error ? err.message : '처리 중 오류');
    } finally {
      setAlwayzLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Upload Section - Two columns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Coupang */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-4">
            <PlatformBadge platform="coupang" />
            <span className="text-sm font-bold text-gray-900">운송장 등록</span>
          </div>
          <p className="text-xs text-gray-500 mb-4">
            해달 발주서(운송장번호 포함)를 업로드하면 쿠팡 상품준비중 주문에 자동 등록합니다.
          </p>
          <div className="mb-4">
            <FileUpload label="해달 발주서 파일" file={coupangFile}
              onFileSelect={(f: File) => { setCoupangFile(f || null); setCoupangResult(null); setCoupangError(''); }} />
          </div>
          <button onClick={handleCoupangUpload} disabled={coupangLoading || !coupangFile}
            className="bg-orange-500 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-orange-600 disabled:opacity-50 transition-all shadow-md shadow-orange-200 flex items-center gap-2">
            {coupangLoading ? '등록 중...' : '쿠팡 운송장 등록'}
          </button>
          {coupangError && <div className="mt-3"><ErrorBanner message={coupangError} /></div>}
          {coupangLoading && <div className="mt-3"><Spinner text="쿠팡 운송장 등록 중..." color="orange" /></div>}
          {coupangResult && <div className="mt-4"><TrackingResultView result={coupangResult} platform="쿠팡" /></div>}
        </div>

        {/* Toss */}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-4">
            <PlatformBadge platform="toss" />
            <span className="text-sm font-bold text-gray-900">운송장 등록</span>
          </div>
          <p className="text-xs text-gray-500 mb-4">
            해달 발주서(운송장번호 포함)를 업로드하면 토스 주문에 자동으로 운송장번호를 등록합니다.
          </p>
          <div className="mb-4">
            <FileUpload label="해달 발주서 파일" file={tossFile}
              onFileSelect={(f: File) => { setTossFile(f || null); setTossResult(null); setTossError(''); }} />
          </div>
          <button onClick={handleTossUpload} disabled={tossLoading || !tossFile}
            className="bg-blue-500 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-blue-600 disabled:opacity-50 transition-all shadow-md shadow-blue-200 flex items-center gap-2">
            {tossLoading ? '등록 중...' : '토스 운송장 등록'}
          </button>
          {tossError && <div className="mt-3"><ErrorBanner message={tossError} /></div>}
          {tossLoading && <div className="mt-3"><Spinner text="토스 운송장 등록 중..." /></div>}
          {tossResult && <div className="mt-4"><TrackingResultView result={tossResult} platform="토스" /></div>}
        </div>
      </div>

      {/* Batch upload button */}
      {(coupangFile || tossFile) && (
        <div className="flex justify-center">
          <button onClick={handleBothUpload} disabled={coupangLoading || tossLoading || (!coupangFile && !tossFile)}
            className="bg-gradient-to-r from-orange-500 to-blue-500 text-white px-8 py-3 rounded-xl font-semibold text-sm
                       hover:from-orange-600 hover:to-blue-600 disabled:opacity-50 transition-all shadow-lg flex items-center gap-2">
            {(coupangLoading || tossLoading) ? '등록 중...' : '전체 운송장 등록'}
          </button>
        </div>
      )}

      {/* Alwayz file-based tracking */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-5">
        <div className="flex items-center gap-2 mb-4">
          <PlatformBadge platform="alwayz" />
          <span className="text-sm font-bold text-gray-900">운송장 입력 (파일)</span>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          해달 발주서(운송장번호 포함)와 올웨이즈 주문 파일을 업로드하면 운송장번호를 자동으로 채워넣습니다.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <FileUpload label="해달 발주서 파일" file={alwayzHaedalFile}
            onFileSelect={(f: File) => { setAlwayzHaedalFile(f || null); setAlwayzStats(null); setAlwayzError(''); }} />
          <FileUpload label="올웨이즈 주문 파일" file={alwayzOrderFile}
            onFileSelect={(f: File) => { setAlwayzOrderFile(f || null); setAlwayzStats(null); setAlwayzError(''); }} />
        </div>
        <button onClick={handleAlwayzUpload} disabled={alwayzLoading || !alwayzHaedalFile || !alwayzOrderFile}
          className="bg-purple-500 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-purple-600 disabled:opacity-50 transition-all shadow-md shadow-purple-200 flex items-center gap-2">
          {alwayzLoading ? '입력 중...' : '올웨이즈 운송장 입력'}
        </button>
        {alwayzError && <div className="mt-3"><ErrorBanner message={alwayzError} /></div>}
        {alwayzLoading && <div className="mt-3"><Spinner text="올웨이즈 운송장 입력 중..." color="purple" /></div>}
        {alwayzStats && (
          <div className="mt-4 animate-fade-in">
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
                <p className="text-2xl font-bold text-green-700">{String(alwayzStats.filled ?? 0)}</p>
                <p className="text-xs font-semibold text-green-600 mt-1">입력 완료</p>
              </div>
              <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
                <p className="text-2xl font-bold text-gray-700">{String(alwayzStats.skipped ?? 0)}</p>
                <p className="text-xs font-semibold text-gray-600 mt-1">스킵</p>
              </div>
              <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-center">
                <p className="text-2xl font-bold text-blue-700">{String(alwayzStats.haedal_entries ?? 0)}</p>
                <p className="text-xs font-semibold text-blue-600 mt-1">해달 건수</p>
              </div>
            </div>
            <p className="text-xs text-green-600 font-semibold mt-3">파일이 자동으로 다운로드됩니다.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// TAB 3: CS 관리 (토스)
// ══════════════════════════════════════════════════════════════════
type ClaimTabId = 'cancel' | 'exchange' | 'return' | 'cs';

const CLAIM_TABS: { id: ClaimTabId; label: string; icon: string }[] = [
  { id: 'cancel', label: '주문취소', icon: '❌' },
  { id: 'exchange', label: '교환', icon: '🔄' },
  { id: 'return', label: '반품', icon: '↩️' },
  { id: 'cs', label: 'CS 현황', icon: '🎧' },
];

function ClaimsTab({ claimType, approveAction, rejectAction }: {
  claimType: string;
  approveAction: (id: number) => Promise<{ status: string }>;
  rejectAction: (id: number, reason: string) => Promise<{ status: string }>;
}) {
  const today = new Date();
  const [fromDate, setFromDate] = useState(formatDate(new Date(today.getTime() - 30 * 86400000)));
  const [toDate, setToDate] = useState(formatDate(today));
  const [claims, setClaims] = useState<TossClaim[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [rejectTarget, setRejectTarget] = useState<number | null>(null);

  const typeLabel = claimType === 'CANCEL' ? '취소' : claimType === 'EXCHANGE' ? '교환' : '반품';

  const handleFetch = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetchTossClaims(fromDate, toDate, claimType);
      setClaims(res.claims);
    } catch (err) {
      setError(err instanceof Error ? err.message : '조회 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (orderProductId: number) => {
    try {
      await approveAction(orderProductId);
      setActionMsg(`${typeLabel} 승인 완료`);
      handleFetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${typeLabel} 승인 실패`);
    }
  };

  const handleReject = async () => {
    if (!rejectTarget || !rejectReason) return;
    try {
      await rejectAction(rejectTarget, rejectReason);
      setActionMsg(`${typeLabel} 거부 완료`);
      setRejectTarget(null);
      setRejectReason('');
      handleFetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${typeLabel} 거부 실패`);
    }
  };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1">시작일</label>
            <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-blue-300 outline-none" />
          </div>
          <div className="pt-5 text-gray-400">~</div>
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1">종료일</label>
            <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-blue-300 outline-none" />
          </div>
        </div>
        <button onClick={handleFetch} disabled={loading}
          className="bg-blue-500 text-white px-6 py-3 rounded-xl font-semibold text-sm hover:bg-blue-600 disabled:opacity-50 transition-all shadow-md shadow-blue-200">
          {loading ? '조회 중...' : `${typeLabel} 요청 조회`}
        </button>
      </div>

      {error && <ErrorBanner message={error} />}
      {actionMsg && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-sm text-green-700 font-semibold animate-fade-in">{actionMsg}</div>
      )}
      {loading && <Spinner text={`${typeLabel} 요청을 조회하고 있습니다...`} />}

      {rejectTarget !== null && (
        <div className="bg-white border border-orange-200 rounded-2xl p-6 shadow-sm animate-fade-in">
          <h4 className="text-sm font-bold text-gray-900 mb-3">{typeLabel} 거부 사유 입력</h4>
          <input value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
            placeholder="거부 사유를 입력하세요"
            className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm mb-3 focus:ring-2 focus:ring-orange-300 outline-none" />
          <div className="flex gap-2">
            <button onClick={handleReject} disabled={!rejectReason}
              className="bg-orange-500 text-white px-5 py-2 rounded-xl font-semibold text-sm hover:bg-orange-600 disabled:opacity-50 transition-all">
              거부 확인
            </button>
            <button onClick={() => { setRejectTarget(null); setRejectReason(''); }}
              className="text-gray-500 px-4 py-2 rounded-xl text-sm hover:bg-gray-100 transition-all">
              취소
            </button>
          </div>
        </div>
      )}

      {!loading && claims.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
          <div className="px-6 py-3 bg-gray-50 border-b border-gray-200">
            <p className="text-sm font-semibold text-gray-700">{typeLabel} 요청 {claims.length}건</p>
          </div>
          <div className="max-h-[500px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">주문번호</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">상품명</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">수취인</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">사유</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">상태</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500">처리</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {claims.map((c, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-700 font-mono text-xs">{c.orderId || '-'}</td>
                    <td className="px-4 py-2 text-gray-900">{c.productName || '-'}</td>
                    <td className="px-4 py-2 text-gray-700">{c.receiverName || '-'}</td>
                    <td className="px-4 py-2 text-gray-600 text-xs">{c.claimReason || '-'}</td>
                    <td className="px-4 py-2">
                      <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-semibold bg-yellow-100 text-yellow-700">
                        {c.claimStatus || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      {c.orderProductId && (
                        <div className="flex gap-1.5">
                          <button onClick={() => handleApprove(c.orderProductId!)}
                            className="px-3 py-1 rounded-lg text-xs font-semibold bg-green-100 text-green-700 hover:bg-green-200 transition-all">
                            승인
                          </button>
                          <button onClick={() => setRejectTarget(c.orderProductId!)}
                            className="px-3 py-1 rounded-lg text-xs font-semibold bg-red-100 text-red-700 hover:bg-red-200 transition-all">
                            거부
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function CSOverviewTab() {
  const today = new Date();
  const fromDate = formatDate(new Date(today.getTime() - 30 * 86400000));
  const toDate = formatDate(today);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<{ cancel: number; exchange: number; return: number } | null>(null);
  const [error, setError] = useState('');

  const handleFetch = async () => {
    setLoading(true);
    setError('');
    try {
      const [cancelRes, exchangeRes, returnRes] = await Promise.all([
        fetchTossClaims(fromDate, toDate, 'CANCEL'),
        fetchTossClaims(fromDate, toDate, 'EXCHANGE'),
        fetchTossClaims(fromDate, toDate, 'RETURN'),
      ]);
      setStats({ cancel: cancelRes.total, exchange: exchangeRes.total, return: returnRes.total });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'CS 현황 조회 실패');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { handleFetch(); }, []);

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-bold text-gray-900">CS 현황 (최근 30일)</h3>
            <p className="text-sm text-gray-500 mt-0.5">{fromDate} ~ {toDate}</p>
          </div>
          <button onClick={handleFetch} disabled={loading}
            className="bg-blue-500 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-blue-600 disabled:opacity-50 transition-all">
            {loading ? '조회 중...' : '새로고침'}
          </button>
        </div>
        {error && <ErrorBanner message={error} />}
        {loading && <Spinner text="CS 현황을 조회하고 있습니다..." />}
        {stats && (
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-red-50 border border-red-200 rounded-2xl p-6 text-center">
              <p className="text-4xl font-bold text-red-700">{stats.cancel}</p>
              <p className="text-sm font-semibold text-red-600 mt-2">주문취소</p>
            </div>
            <div className="bg-orange-50 border border-orange-200 rounded-2xl p-6 text-center">
              <p className="text-4xl font-bold text-orange-700">{stats.exchange}</p>
              <p className="text-sm font-semibold text-orange-600 mt-2">교환</p>
            </div>
            <div className="bg-yellow-50 border border-yellow-200 rounded-2xl p-6 text-center">
              <p className="text-4xl font-bold text-yellow-700">{stats.return}</p>
              <p className="text-sm font-semibold text-yellow-600 mt-2">반품</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function CSManagementTab() {
  const [activeClaimTab, setActiveClaimTab] = useState<ClaimTabId>('cancel');

  return (
    <div className="space-y-4">
      {/* Sub-tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1">
        {CLAIM_TABS.map((tab) => (
          <button key={tab.id} onClick={() => setActiveClaimTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold transition-all ${
              activeClaimTab === tab.id
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}>
            <span>{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 mb-2">
        <PlatformBadge platform="toss" />
        <span className="text-xs text-gray-500">토스 플랫폼에서만 CS 관리가 가능합니다</span>
      </div>

      {activeClaimTab === 'cancel' && <ClaimsTab claimType="CANCEL" approveAction={approveTossCancel} rejectAction={rejectTossCancel} />}
      {activeClaimTab === 'exchange' && <ClaimsTab claimType="EXCHANGE" approveAction={approveTossExchange} rejectAction={rejectTossExchange} />}
      {activeClaimTab === 'return' && <ClaimsTab claimType="RETURN" approveAction={approveTossReturn} rejectAction={rejectTossReturn} />}
      {activeClaimTab === 'cs' && <CSOverviewTab />}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// MAIN: GogumaUnifiedPage
// ══════════════════════════════════════════════════════════════════
type MainTabId = 'orders' | 'tracking' | 'claims';

const MAIN_TABS: { id: MainTabId; label: string; icon: string; desc: string }[] = [
  { id: 'orders', label: '발주서 생성', icon: '📋', desc: '쿠팡 + 토스 주문 수집' },
  { id: 'tracking', label: '운송장 등록', icon: '📦', desc: '쿠팡 + 토스 + 올웨이즈 운송장 입력' },
  { id: 'claims', label: 'CS 관리', icon: '🎧', desc: '취소/교환/반품 처리' },
];

function GogumaUnifiedPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<MainTabId>('orders');
  const [tossStatus, setTossStatus] = useState<'checking' | 'ok' | 'error'>('checking');
  const [tossMsg, setTossMsg] = useState('');

  const refreshTossConnection = useCallback(() => {
    testTossConnection().then((res) => {
      setTossStatus(res.status === 'ok' ? 'ok' : 'error');
      setTossMsg(res.message);
    }).catch(() => {
      setTossStatus('error');
      setTossMsg('연결 확인 실패');
    });
  }, []);

  useEffect(() => {
    refreshTossConnection();

    const intervalId = window.setInterval(refreshTossConnection, 30000);
    const handleFocus = () => refreshTossConnection();
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshTossConnection();
      }
    };

    window.addEventListener('focus', handleFocus);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener('focus', handleFocus);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [refreshTossConnection]);

  return (
    <div>
      {/* Back Button */}
      <button onClick={() => navigate('/orders')}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 font-medium mb-6 group">
        <svg className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        도구 목록으로 돌아가기
      </button>

      {/* Header */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 mb-6 animate-slide-up">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-gradient-to-br from-orange-100 to-blue-100 rounded-2xl flex items-center justify-center text-3xl">
              🍠
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">고구마 통합 대시보드</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                쿠팡 + 토스 주문을 한 화면에서 관리합니다
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Coupang status (always ok if app loads) */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-green-100 text-green-700">
              <div className="w-2 h-2 rounded-full bg-green-500" />
              쿠팡 API
            </div>
            {/* Toss status */}
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold ${
              tossStatus === 'ok' ? 'bg-green-100 text-green-700' :
              tossStatus === 'error' ? 'bg-red-100 text-red-700' :
              'bg-gray-100 text-gray-500'
            }`}>
              <div className={`w-2 h-2 rounded-full ${
                tossStatus === 'ok' ? 'bg-green-500' :
                tossStatus === 'error' ? 'bg-red-500' :
                'bg-gray-400 animate-pulse'
              }`} />
              {tossStatus === 'checking' ? '토스 확인 중...' :
               tossStatus === 'ok' ? '토스 API' : '토스 오류'}
            </div>
          </div>
        </div>
      </div>

      {/* Toss Connection Error */}
      {tossStatus === 'error' && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 mb-6 animate-fade-in">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm text-amber-800 font-semibold">
                토스 API 연결 실패 — 토스 관련 기능이 제한될 수 있습니다.
              </p>
              <p className="text-xs text-amber-600 mt-1">{tossMsg}</p>
            </div>
            <button
              onClick={refreshTossConnection}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-white border border-amber-200 text-xs font-semibold text-amber-700 hover:bg-amber-100 transition-colors"
            >
              다시 확인
            </button>
          </div>
        </div>
      )}

      {/* Main Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-2xl p-1.5 mb-6">
        {MAIN_TABS.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-semibold transition-all duration-200 ${
              activeTab === tab.id
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            <span className="text-lg">{tab.icon}</span>
            <div className="text-left">
              <div>{tab.label}</div>
              <div className={`text-[10px] font-medium ${activeTab === tab.id ? 'text-gray-500' : 'text-gray-400'}`}>
                {tab.desc}
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'orders' && <OrderCollectionTab />}
      {activeTab === 'tracking' && <TrackingTab />}
      {activeTab === 'claims' && <CSManagementTab />}
    </div>
  );
}

export default GogumaUnifiedPage;
