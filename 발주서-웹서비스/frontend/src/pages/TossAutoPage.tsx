import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  processTossOrder, processTossTrackingApi, downloadBlob,
  ProcessResult, TrackingApiResult,
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

type TabId = 'orders' | 'tracking' | 'cancel' | 'exchange' | 'return' | 'cs';

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'orders', label: '주문수집', icon: '📋' },
  { id: 'tracking', label: '운송장입력', icon: '📦' },
  { id: 'cancel', label: '주문취소', icon: '❌' },
  { id: 'exchange', label: '교환', icon: '🔄' },
  { id: 'return', label: '반품', icon: '↩️' },
  { id: 'cs', label: 'CS', icon: '🎧' },
];

const ORDER_STATUSES = [
  { value: '', label: '전체' },
  { value: 'PAID', label: '결제완료' },
  { value: 'PREPARING_PRODUCT', label: '상품준비중' },
  { value: 'DELIVERING', label: '배송중' },
  { value: 'DELIVERED', label: '배송완료' },
];

// ── Spinner ──────────────────────────────────────────────────────
function Spinner({ text }: { text: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center animate-fade-in">
      <svg className="animate-spin w-10 h-10 text-blue-500 mx-auto mb-4" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <p className="text-sm font-semibold text-gray-900">{text}</p>
    </div>
  );
}

// ── Error Banner ─────────────────────────────────────────────────
function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-2xl p-5 mb-6 animate-fade-in">
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

// ── Orders Tab ───────────────────────────────────────────────────
function OrdersTab() {
  const today = new Date();
  const [fromDate, setFromDate] = useState(formatDate(today));
  const [toDate, setToDate] = useState(formatDate(today));
  const [orderStatus, setOrderStatus] = useState('');
  const [loading, setLoading] = useState(false);
  const [orders, setOrders] = useState<TossOrder[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState('');
  // Legacy: order collection (발주서 생성)
  const [collectLoading, setCollectLoading] = useState(false);
  const [collectResult, setCollectResult] = useState<ProcessResult | null>(null);

  const setDateRange = useCallback((days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setFromDate(formatDate(start));
    setToDate(formatDate(end));
  }, []);

  const handleFetch = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetchTossOrders(fromDate, toDate, orderStatus || undefined);
      setOrders(res.orders);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '주문 조회 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleCollect = async () => {
    setCollectLoading(true);
    setError('');
    setCollectResult(null);
    try {
      const res = await processTossOrder(fromDate, toDate);
      setCollectResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : '발주서 생성 실패');
    } finally {
      setCollectLoading(false);
    }
  };

  const quickButtons = [
    { days: 1, label: '오늘' },
    { days: 2, label: '2일' },
    { days: 3, label: '3일' },
    { days: 7, label: '7일' },
    { days: 30, label: '30일' },
  ];

  return (
    <div className="space-y-4">
      {/* Date & Status Filter */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <div className="flex gap-2 mb-4">
          {quickButtons.map(({ days, label }) => (
            <button key={days} onClick={() => setDateRange(days)}
              className="px-4 py-2 rounded-xl font-semibold text-sm bg-gray-100 text-gray-600 hover:bg-gray-200 transition-all">
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 mb-4">
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1">시작일</label>
            <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} max={toDate}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-blue-300 outline-none" />
          </div>
          <div className="pt-5 text-gray-400">~</div>
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1">종료일</label>
            <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} min={fromDate} max={formatDate(today)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-blue-300 outline-none" />
          </div>
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1">주문 상태</label>
            <select value={orderStatus} onChange={(e) => setOrderStatus(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-blue-300 outline-none">
              {ORDER_STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
        </div>
        <div className="flex gap-3">
          <button onClick={handleFetch} disabled={loading}
            className="bg-blue-500 text-white px-6 py-3 rounded-xl font-semibold text-sm hover:bg-blue-600 disabled:opacity-50 transition-all flex items-center gap-2 shadow-md shadow-blue-200">
            {loading ? '조회 중...' : '주문 조회'}
          </button>
          <button onClick={handleCollect} disabled={collectLoading}
            className="bg-indigo-500 text-white px-6 py-3 rounded-xl font-semibold text-sm hover:bg-indigo-600 disabled:opacity-50 transition-all flex items-center gap-2 shadow-md shadow-indigo-200">
            {collectLoading ? '생성 중...' : '고구마 발주서 생성'}
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {loading && <Spinner text="토스 주문을 조회하고 있습니다..." />}

      {/* Collect Result */}
      {collectResult && (
        <div className="bg-green-50 border border-green-200 rounded-2xl p-5 animate-fade-in">
          <h4 className="text-sm font-bold text-green-800 mb-2">발주서 생성 완료</h4>
          {collectResult.stats && Object.entries(collectResult.stats).map(([k, v]) => (
            <p key={k} className="text-sm text-green-700">{k}: {String(v)}</p>
          ))}
          <button onClick={() => downloadBlob(collectResult.blob, collectResult.filename)}
            className="mt-3 bg-green-600 text-white px-5 py-2 rounded-xl font-semibold text-sm hover:bg-green-700 transition-all">
            {collectResult.filename} 다운로드
          </button>
        </div>
      )}

      {/* Orders Table */}
      {!loading && orders.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
          <div className="px-6 py-3 bg-gray-50 border-b border-gray-200">
            <p className="text-sm font-semibold text-gray-700">총 {total}건</p>
          </div>
          <div className="max-h-[500px] overflow-y-auto">
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
                {orders.map((o, i) => (
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

      {!loading && orders.length === 0 && total === 0 && !error && (
        <div className="text-center py-12 text-gray-400 text-sm">
          주문을 조회하려면 날짜를 선택하고 "주문 조회" 버튼을 클릭하세요.
        </div>
      )}
    </div>
  );
}

// ── Tracking Tab ─────────────────────────────────────────────────
function TrackingTab() {
  const [trackingFile, setTrackingFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TrackingApiResult | null>(null);
  const [error, setError] = useState('');

  const handleUpload = async () => {
    if (!trackingFile) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await processTossTrackingApi(trackingFile);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : '처리 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setTrackingFile(null);
    setResult(null);
    setError('');
  };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 bg-indigo-50 rounded-2xl flex items-center justify-center text-3xl">📦</div>
          <div>
            <h3 className="text-lg font-bold text-gray-900">토스 운송장번호 자동 등록</h3>
            <p className="text-sm text-gray-500 mt-0.5">
              해달 발주서(운송장번호 포함)를 업로드하면 토스 주문에 자동으로 운송장번호를 등록합니다.
            </p>
          </div>
        </div>
        <div className="mb-5">
          <FileUpload label="해달 발주서 파일 (운송장번호 포함)" file={trackingFile} onFileSelect={(f: File) => { setTrackingFile(f || null); setResult(null); setError(''); }} />
        </div>
        <div className="flex items-center gap-3">
          <button onClick={handleUpload} disabled={loading || !trackingFile}
            className="bg-indigo-500 text-white px-6 py-3 rounded-xl font-semibold text-sm hover:bg-indigo-600 disabled:opacity-50 transition-all flex items-center gap-2 shadow-md shadow-indigo-200">
            {loading ? '등록 중...' : '토스 운송장 등록'}
          </button>
          {(result || error) && (
            <button onClick={handleReset} className="text-gray-500 hover:text-gray-700 px-4 py-3 rounded-xl text-sm hover:bg-gray-100 transition-all">초기화</button>
          )}
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {loading && <Spinner text="토스 주문을 조회하고 운송장번호를 등록하고 있습니다..." />}

      {result && (
        <div className="animate-fade-in space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-green-700">{result.success}</p>
              <p className="text-xs font-semibold text-green-600 mt-1">등록 성공</p>
            </div>
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-red-700">{result.fail}</p>
              <p className="text-xs font-semibold text-red-600 mt-1">등록 실패</p>
            </div>
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-gray-700">{result.skip}</p>
              <p className="text-xs font-semibold text-gray-600 mt-1">스킵</p>
            </div>
          </div>
          {result.results.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="max-h-80 overflow-y-auto">
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
                      <tr key={i} className={r.status === 'success' ? 'bg-green-50/50' : r.status === 'fail' ? 'bg-red-50/50' : ''}>
                        <td className="px-4 py-2 font-medium text-gray-900">{r.name}</td>
                        <td className="px-4 py-2 text-gray-600 font-mono text-xs">{r.tracking || '-'}</td>
                        <td className="px-4 py-2">
                          <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-semibold ${
                            r.status === 'success' ? 'bg-green-100 text-green-700' : r.status === 'fail' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-600'
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
      )}
    </div>
  );
}

// ── Claims Tab (Cancel / Exchange / Return) ──────────────────────
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
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-sm text-green-700 font-semibold animate-fade-in">
          {actionMsg}
        </div>
      )}
      {loading && <Spinner text={`${typeLabel} 요청을 조회하고 있습니다...`} />}

      {/* Reject Modal */}
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

      {/* Claims Table */}
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

      {!loading && claims.length === 0 && !error && (
        <div className="text-center py-12 text-gray-400 text-sm">
          {typeLabel} 요청을 조회하려면 날짜를 선택하고 조회 버튼을 클릭하세요.
        </div>
      )}
    </div>
  );
}

// ── CS Tab ───────────────────────────────────────────────────────
function CSTab() {
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
      setStats({
        cancel: cancelRes.total,
        exchange: exchangeRes.total,
        return: returnRes.total,
      });
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

// ── Main Component ───────────────────────────────────────────────
function TossAutoPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabId>('orders');
  const [connectionStatus, setConnectionStatus] = useState<'checking' | 'ok' | 'error'>('checking');
  const [connectionMsg, setConnectionMsg] = useState('');

  useEffect(() => {
    testTossConnection().then((res) => {
      setConnectionStatus(res.status === 'ok' ? 'ok' : 'error');
      setConnectionMsg(res.message);
    }).catch(() => {
      setConnectionStatus('error');
      setConnectionMsg('연결 확인 실패');
    });
  }, []);

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
            <div className="w-14 h-14 bg-blue-50 rounded-2xl flex items-center justify-center text-3xl">
              <img src="https://static.toss.im/icons/png/4x/icon-toss-logo.png" alt="토스" className="w-8 h-8"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; (e.target as HTMLImageElement).parentElement!.textContent = '🛒'; }} />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">토스 주문관리 대시보드</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                주문수집, 운송장입력, 취소/교환/반품 관리를 한 곳에서 처리합니다.
              </p>
            </div>
          </div>
          {/* Connection Status */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold ${
            connectionStatus === 'ok' ? 'bg-green-100 text-green-700' :
            connectionStatus === 'error' ? 'bg-red-100 text-red-700' :
            'bg-gray-100 text-gray-500'
          }`}>
            <div className={`w-2 h-2 rounded-full ${
              connectionStatus === 'ok' ? 'bg-green-500' :
              connectionStatus === 'error' ? 'bg-red-500' :
              'bg-gray-400 animate-pulse'
            }`} />
            {connectionStatus === 'checking' ? 'API 연결 확인 중...' :
             connectionStatus === 'ok' ? 'API 연결됨' : connectionMsg}
          </div>
        </div>
      </div>

      {/* Connection Error Banner */}
      {connectionStatus === 'error' && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 mb-6 animate-fade-in">
          <p className="text-sm text-amber-800 font-semibold">
            토스 API 연결에 실패했습니다. 환경변수(TOSS_ACCESS_KEY, TOSS_SECRET_KEY)를 확인하세요.
          </p>
          <p className="text-xs text-amber-600 mt-1">{connectionMsg}</p>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex gap-1 bg-gray-100 rounded-2xl p-1.5 mb-6">
        {TABS.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
              activeTab === tab.id
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'
            }`}>
            <span className="text-base">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'orders' && <OrdersTab />}
      {activeTab === 'tracking' && <TrackingTab />}
      {activeTab === 'cancel' && <ClaimsTab claimType="CANCEL" approveAction={approveTossCancel} rejectAction={rejectTossCancel} />}
      {activeTab === 'exchange' && <ClaimsTab claimType="EXCHANGE" approveAction={approveTossExchange} rejectAction={rejectTossExchange} />}
      {activeTab === 'return' && <ClaimsTab claimType="RETURN" approveAction={approveTossReturn} rejectAction={rejectTossReturn} />}
      {activeTab === 'cs' && <CSTab />}
    </div>
  );
}

export default TossAutoPage;
