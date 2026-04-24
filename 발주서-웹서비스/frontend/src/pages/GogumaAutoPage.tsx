import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { processGogumaAuto, processGogumaTrackingApi, downloadBlob, ProcessResult, TrackingApiResult } from '../api';
import FileUpload from '../components/FileUpload';

function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function GogumaAutoPage() {
  const navigate = useNavigate();
  const today = new Date();

  const [fromDate, setFromDate] = useState(formatDate(today));
  const [toDate, setToDate] = useState(formatDate(today));
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState('');

  const setDateRange = useCallback((days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - (days - 1));
    setFromDate(formatDate(start));
    setToDate(formatDate(end));
    setResult(null);
    setError('');
  }, []);

  const handleCollect = async () => {
    setLoading(true);
    setError('');
    setResult(null);

    try {
      const res = await processGogumaAuto(fromDate, toDate);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : '처리 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (result) {
      downloadBlob(result.blob, result.filename);
    }
  };

  const handleReset = () => {
    setFromDate(formatDate(today));
    setToDate(formatDate(today));
    setResult(null);
    setError('');
  };

  // --- Tracking API State ---
  const [trackingFile, setTrackingFile] = useState<File | null>(null);
  const [trackingLoading, setTrackingLoading] = useState(false);
  const [trackingResult, setTrackingResult] = useState<TrackingApiResult | null>(null);
  const [trackingError, setTrackingError] = useState('');

  const handleTrackingUpload = async () => {
    if (!trackingFile) return;
    setTrackingLoading(true);
    setTrackingError('');
    setTrackingResult(null);

    try {
      const res = await processGogumaTrackingApi(trackingFile);
      setTrackingResult(res);
    } catch (err) {
      setTrackingError(err instanceof Error ? err.message : '처리 중 오류가 발생했습니다.');
    } finally {
      setTrackingLoading(false);
    }
  };

  const handleTrackingFileSelect = (file: File) => {
    setTrackingFile(file || null);
    setTrackingResult(null);
    setTrackingError('');
  };

  const handleTrackingReset = () => {
    setTrackingFile(null);
    setTrackingResult(null);
    setTrackingError('');
  };

  // Which quick button is active?
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

  return (
    <div>
      {/* Back Button */}
      <button
        onClick={() => navigate('/orders')}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700
                   font-medium mb-6 group"
      >
        <svg
          className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        도구 목록으로 돌아가기
      </button>

      {/* Header */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 mb-6 animate-slide-up">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 bg-orange-50 rounded-2xl flex items-center justify-center text-3xl">
            🍠⚡
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900">고구마 자동 발주서 생성</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              쿠팡 API에서 결제완료 주문을 자동 수집하여 해달 발주서를 생성합니다.
            </p>
          </div>
        </div>
      </div>

      {/* Date Selection */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 mb-6 animate-slide-up">
        <h3 className="text-base font-bold text-gray-900 mb-4">기간 선택</h3>

        {/* Quick Buttons */}
        <div className="flex gap-2 mb-5">
          {quickButtons.map(({ days, label, sub }) => (
            <button
              key={days}
              onClick={() => setDateRange(days)}
              className={`px-5 py-2.5 rounded-xl font-semibold text-sm transition-all duration-200 text-center
                ${activeDays === days
                  ? 'bg-orange-500 text-white shadow-md shadow-orange-200'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
            >
              {label}
              {sub && (
                <span className={`block text-[10px] font-medium mt-0.5 ${
                  activeDays === days ? 'text-orange-100' : 'text-gray-400'
                }`}>
                  {sub}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Calendar Inputs */}
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1.5">시작일</label>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => {
                setFromDate(e.target.value);
                setResult(null);
                setError('');
              }}
              max={toDate}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm
                         focus:ring-2 focus:ring-orange-300 focus:border-orange-400 outline-none
                         transition-all"
            />
          </div>
          <div className="pt-5 text-gray-400 font-medium">~</div>
          <div className="flex-1">
            <label className="block text-xs font-semibold text-gray-500 mb-1.5">종료일</label>
            <input
              type="date"
              value={toDate}
              onChange={(e) => {
                setToDate(e.target.value);
                setResult(null);
                setError('');
              }}
              min={fromDate}
              max={formatDate(today)}
              className="w-full px-4 py-2.5 rounded-xl border border-gray-300 text-sm
                         focus:ring-2 focus:ring-orange-300 focus:border-orange-400 outline-none
                         transition-all"
            />
          </div>
        </div>

        {/* Selected Range Display */}
        <div className="mt-4 px-4 py-2.5 bg-orange-50 rounded-xl">
          <p className="text-sm text-orange-700">
            <span className="font-semibold">수집 기간:</span>{' '}
            {fromDate} ~ {toDate}
            {fromDate === toDate && ' (당일)'}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="mt-6 flex items-center gap-3">
          <button
            onClick={handleCollect}
            disabled={loading || !fromDate || !toDate}
            className="bg-orange-500 text-white px-6 py-3 rounded-xl font-semibold text-sm
                       hover:bg-orange-600 active:bg-orange-700
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all duration-200
                       flex items-center gap-2 shadow-md shadow-orange-200"
          >
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10"
                    stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                주문 수집 중...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                주문 수집
              </>
            )}
          </button>
          {(result || error) && (
            <button
              onClick={handleReset}
              disabled={loading}
              className="text-gray-500 hover:text-gray-700 px-4 py-3 rounded-xl
                         font-medium text-sm hover:bg-gray-100
                         disabled:opacity-50 disabled:cursor-not-allowed
                         transition-all duration-200"
            >
              초기화
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-5 mb-6 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-red-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24"
                stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.07 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <div>
              <h4 className="text-sm font-bold text-red-800 mb-0.5">오류 발생</h4>
              <p className="text-sm text-red-600">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Success */}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-2xl p-5 mb-6 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-green-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24"
                stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div className="flex-1">
              <h4 className="text-sm font-bold text-green-800 mb-1">주문 수집 완료</h4>
              {result.stats && (
                <div className="space-y-0.5 mb-3">
                  {Object.entries(result.stats).map(([key, value]) => (
                    <p key={key} className="text-sm text-green-700">
                      {key === 'total' ? `수집된 주문: ${value}건` :
                       key === 'period' ? `수집 기간: ${value}` :
                       `${key}: ${value}`}
                    </p>
                  ))}
                </div>
              )}
              <button
                onClick={handleDownload}
                className="inline-flex items-center gap-2 bg-green-600 text-white
                           px-5 py-2.5 rounded-xl font-semibold text-sm
                           hover:bg-green-700 active:bg-green-800
                           transition-all duration-200 shadow-sm"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {result.filename} 다운로드
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center animate-fade-in">
          <svg className="animate-spin w-10 h-10 text-orange-500 mx-auto mb-4"
            fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10"
              stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-sm font-semibold text-gray-900">
            쿠팡 API에서 결제완료 주문을 수집하고 있습니다...
          </p>
          <p className="text-xs text-gray-500 mt-1">잠시만 기다려주세요</p>
        </div>
      )}

      {/* ====== Divider ====== */}
      <div className="relative my-10">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-gray-200" />
        </div>
        <div className="relative flex justify-center">
          <span className="bg-gray-50 px-4 text-xs font-semibold text-gray-400 uppercase tracking-wider">
            운송장 등록
          </span>
        </div>
      </div>

      {/* ====== Tracking Upload Section ====== */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 mb-6 animate-slide-up">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 bg-blue-50 rounded-2xl flex items-center justify-center text-3xl">
            🍠📦
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900">운송장번호 자동 등록</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              해달 발주서(운송장번호 포함)를 업로드하면 쿠팡 상품준비중 주문에 자동으로 운송장번호를 등록합니다.
            </p>
          </div>
        </div>

        {/* File Upload */}
        <div className="mb-5">
          <FileUpload
            label="해달 발주서 파일 (운송장번호 포함)"
            file={trackingFile}
            onFileSelect={handleTrackingFileSelect}
          />
        </div>

        {/* Action Button */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleTrackingUpload}
            disabled={trackingLoading || !trackingFile}
            className="bg-blue-500 text-white px-6 py-3 rounded-xl font-semibold text-sm
                       hover:bg-blue-600 active:bg-blue-700
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all duration-200
                       flex items-center gap-2 shadow-md shadow-blue-200"
          >
            {trackingLoading ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10"
                    stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                운송장 등록 중...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                쿠팡 운송장 등록
              </>
            )}
          </button>
          {(trackingResult || trackingError) && (
            <button
              onClick={handleTrackingReset}
              disabled={trackingLoading}
              className="text-gray-500 hover:text-gray-700 px-4 py-3 rounded-xl
                         font-medium text-sm hover:bg-gray-100
                         disabled:opacity-50 disabled:cursor-not-allowed
                         transition-all duration-200"
            >
              초기화
            </button>
          )}
        </div>
      </div>

      {/* Tracking Error */}
      {trackingError && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-5 mb-6 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-red-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24"
                stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.07 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <div>
              <h4 className="text-sm font-bold text-red-800 mb-0.5">오류 발생</h4>
              <p className="text-sm text-red-600">{trackingError}</p>
            </div>
          </div>
        </div>
      )}

      {/* Tracking Loading */}
      {trackingLoading && (
        <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center animate-fade-in mb-6">
          <svg className="animate-spin w-10 h-10 text-blue-500 mx-auto mb-4"
            fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10"
              stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-sm font-semibold text-gray-900">
            쿠팡 상품준비중 주문을 조회하고 운송장번호를 등록하고 있습니다...
          </p>
          <p className="text-xs text-gray-500 mt-1">잠시만 기다려주세요</p>
        </div>
      )}

      {/* Tracking Result */}
      {trackingResult && (
        <div className="animate-fade-in space-y-4">
          {/* Summary Cards */}
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-green-700">{trackingResult.success}</p>
              <p className="text-xs font-semibold text-green-600 mt-1">등록 성공</p>
            </div>
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-red-700">{trackingResult.fail}</p>
              <p className="text-xs font-semibold text-red-600 mt-1">등록 실패</p>
            </div>
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-gray-700">{trackingResult.skip}</p>
              <p className="text-xs font-semibold text-gray-600 mt-1">스킵</p>
            </div>
          </div>

          {/* Info Row */}
          <div className="flex gap-4 text-xs text-gray-500">
            <span>해달 운송장: <strong className="text-gray-700">{trackingResult.haedal_entries}건</strong></span>
            <span>쿠팡 상품준비중: <strong className="text-gray-700">{trackingResult.coupang_orders}건</strong></span>
          </div>

          {/* Detail Table */}
          {trackingResult.results.length > 0 && (
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
                    {trackingResult.results.map((r, i) => (
                      <tr key={i} className={
                        r.status === 'success' ? 'bg-green-50/50' :
                        r.status === 'fail' ? 'bg-red-50/50' : ''
                      }>
                        <td className="px-4 py-2 font-medium text-gray-900">{r.name}</td>
                        <td className="px-4 py-2 text-gray-600 font-mono text-xs">
                          {r.tracking || '-'}
                        </td>
                        <td className="px-4 py-2">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold
                            ${r.status === 'success' ? 'bg-green-100 text-green-700' :
                              r.status === 'fail' ? 'bg-red-100 text-red-700' :
                              'bg-gray-100 text-gray-600'
                            }`}>
                            {r.status === 'success' ? '성공' :
                             r.status === 'fail' ? '실패' : '스킵'}
                          </span>
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

export default GogumaAutoPage;
