import { useState } from 'react';
import { CheckCircle2, XCircle, Loader2, Package } from 'lucide-react';
import { processFile, downloadBlob } from '../api';

/* ── 거래처 설정 (고구마 제외) ────────────────────────────────── */
interface FileSlot {
  key: string;
  label: string;
}

interface VendorConfig {
  id: string;
  toolId: string;
  label: string;
  icon: string;
  color: {
    border: string;
    header: string;
    badge: string;
    dot: string;
  };
  files: FileSlot[];
}

const VENDORS: VendorConfig[] = [
  {
    id: 'chamdureup',
    toolId: 'chamdureup-tracking',
    label: '참두릅',
    icon: '🌱',
    color: {
      border: 'border-green-200',
      header: 'bg-green-50',
      badge: 'bg-green-100 text-green-700',
      dot: 'bg-green-500',
    },
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'myeongi',
    toolId: 'myeongi-tracking',
    label: '명이나물',
    icon: '🌿',
    color: {
      border: 'border-emerald-200',
      header: 'bg-emerald-50',
      badge: 'bg-emerald-100 text-emerald-700',
      dot: 'bg-emerald-500',
    },
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'kolrabi',
    toolId: 'tracking-input',
    label: '콜라비',
    icon: '🥬',
    color: {
      border: 'border-blue-200',
      header: 'bg-blue-50',
      badge: 'bg-blue-100 text-blue-700',
      dot: 'bg-blue-500',
    },
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'tomato',
    toolId: 'tomato-tracking',
    label: '대저토마토·성주참외·남해땅두릅',
    icon: '🍅🍈🌿',
    color: {
      border: 'border-red-200',
      header: 'bg-red-50',
      badge: 'bg-red-100 text-red-700',
      dot: 'bg-red-500',
    },
    files: [
      { key: 'tomato_reply', label: '회신 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'gaegeolmu',
    toolId: 'gaegeolmu-tracking',
    label: '게걸무씨앗기름',
    icon: '🌾',
    color: {
      border: 'border-amber-200',
      header: 'bg-amber-50',
      badge: 'bg-amber-100 text-amber-700',
      dot: 'bg-amber-500',
    },
    files: [
      { key: 'tracking', label: '택배발송 파일 (B=운송장, C=이름)' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
];

/* ── 상태 타입 ───────────────────────────────────────────────── */
type VendorStatus = 'idle' | 'processing' | 'done' | 'error';

interface VendorResult {
  status: VendorStatus;
  message?: string;
}

/* ── 컴팩트 파일 드롭존 ────────────────────────────────────────── */
function CompactFileSlot({
  label,
  file,
  onSelect,
  disabled,
}: {
  label: string;
  file: File | null;
  onSelect: (f: File | null) => void;
  disabled: boolean;
}) {
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (disabled) return;
    const f = e.dataTransfer.files[0];
    if (f) onSelect(f);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) onSelect(f);
    e.target.value = '';
  };

  return (
    <label
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs cursor-pointer transition-colors
        ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        ${
          file
            ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
            : 'border-dashed border-slate-300 bg-slate-50 text-slate-500 hover:border-indigo-300 hover:bg-indigo-50'
        }`}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
    >
      <input
        type="file"
        accept=".xlsx,.xls"
        className="hidden"
        onChange={handleChange}
        disabled={disabled}
      />
      {file ? (
        <>
          <svg className="w-3.5 h-3.5 text-indigo-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span className="truncate max-w-[140px] font-medium">{file.name}</span>
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); onSelect(null); }}
            className="ml-auto text-indigo-400 hover:text-red-500 shrink-0"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </>
      ) : (
        <>
          <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
          </svg>
          <span>{label}</span>
        </>
      )}
    </label>
  );
}

/* ── 메인 페이지 ─────────────────────────────────────────────── */
function BatchTrackingPage() {
  // vendorFiles[vendorId][fileKey] = File | null
  const [vendorFiles, setVendorFiles] = useState<Record<string, Record<string, File | null>>>(
    () => Object.fromEntries(VENDORS.map((v) => [v.id, Object.fromEntries(v.files.map((f) => [f.key, null]))]))
  );
  const [results, setResults] = useState<Record<string, VendorResult>>(
    () => Object.fromEntries(VENDORS.map((v) => [v.id, { status: 'idle' }]))
  );
  const [processing, setProcessing] = useState(false);

  const setFile = (vendorId: string, fileKey: string, file: File | null) => {
    setVendorFiles((prev) => ({
      ...prev,
      [vendorId]: { ...prev[vendorId], [fileKey]: file },
    }));
    // 파일 변경 시 해당 거래처 결과 초기화
    setResults((prev) => ({
      ...prev,
      [vendorId]: { status: 'idle' },
    }));
  };

  // 모든 필수 파일이 있는 거래처 목록
  const readyVendors = VENDORS.filter((v) =>
    v.files.every((f) => vendorFiles[v.id]?.[f.key] != null)
  );

  const handleProcess = async () => {
    if (readyVendors.length === 0) return;
    setProcessing(true);

    // 준비된 거래처 순차 처리 (서버 부하 방지)
    for (const vendor of readyVendors) {
      setResults((prev) => ({ ...prev, [vendor.id]: { status: 'processing' } }));
      try {
        const files = Object.fromEntries(
          Object.entries(vendorFiles[vendor.id]).filter(([, f]) => f != null)
        ) as Record<string, File>;

        const result = await processFile(vendor.toolId, files);
        downloadBlob(result.blob, result.filename);

        const stats = result.stats;
        const msg = stats
          ? `${stats.filled ?? stats.success ?? 0}건 처리 완료`
          : '처리 완료';

        setResults((prev) => ({ ...prev, [vendor.id]: { status: 'done', message: msg } }));
      } catch (err) {
        const msg = err instanceof Error ? err.message : '처리 실패';
        setResults((prev) => ({ ...prev, [vendor.id]: { status: 'error', message: msg } }));
      }
    }

    setProcessing(false);
  };

  const handleClearAll = () => {
    setVendorFiles(
      Object.fromEntries(VENDORS.map((v) => [v.id, Object.fromEntries(v.files.map((f) => [f.key, null]))]))
    );
    setResults(Object.fromEntries(VENDORS.map((v) => [v.id, { status: 'idle' }])));
  };

  const doneCount = Object.values(results).filter((r) => r.status === 'done').length;
  const errorCount = Object.values(results).filter((r) => r.status === 'error').length;
  const allDone = processing === false && doneCount + errorCount === readyVendors.length && readyVendors.length > 0 && doneCount + errorCount > 0;

  return (
    <div className="max-w-3xl mx-auto">
      {/* 헤더 */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-10 h-10 bg-indigo-600 rounded-xl flex items-center justify-center shadow-sm">
            <Package size={20} className="text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-800">일괄 운송장 입력</h2>
            <p className="text-sm text-slate-500">거래처별 파일을 올리면 한 번에 처리합니다 (고구마 제외)</p>
          </div>
        </div>
      </div>

      {/* 안내 */}
      <div className="bg-indigo-50 border border-indigo-100 rounded-xl px-4 py-3 mb-6 text-sm text-indigo-700">
        처리할 거래처의 파일만 올려주세요. 파일이 없는 거래처는 자동으로 건너뜁니다.
      </div>

      {/* 거래처 카드 목록 */}
      <div className="flex flex-col gap-4 mb-6">
        {VENDORS.map((vendor) => {
          const result = results[vendor.id];
          const files = vendorFiles[vendor.id];
          const isReady = vendor.files.every((f) => files[f.key] != null);
          const isProcessing = result.status === 'processing';
          const isDone = result.status === 'done';
          const isError = result.status === 'error';

          return (
            <div
              key={vendor.id}
              className={`bg-white rounded-2xl border ${vendor.color.border} shadow-sm overflow-hidden
                ${isDone ? 'opacity-75' : ''}`}
            >
              {/* 카드 헤더 */}
              <div className={`${vendor.color.header} px-4 py-3 flex items-center justify-between`}>
                <div className="flex items-center gap-2">
                  <span className="text-lg leading-none">{vendor.icon}</span>
                  <span className="font-semibold text-slate-800 text-sm">{vendor.label}</span>
                  {isReady && result.status === 'idle' && (
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${vendor.color.badge}`}>
                      준비됨
                    </span>
                  )}
                </div>
                {/* 상태 표시 */}
                <div className="flex items-center gap-1.5">
                  {isProcessing && (
                    <span className="flex items-center gap-1 text-xs text-indigo-600 font-medium">
                      <Loader2 size={13} className="animate-spin" /> 처리중…
                    </span>
                  )}
                  {isDone && (
                    <span className="flex items-center gap-1 text-xs text-emerald-600 font-medium">
                      <CheckCircle2 size={13} /> {result.message}
                    </span>
                  )}
                  {isError && (
                    <span className="flex items-center gap-1 text-xs text-red-600 font-medium">
                      <XCircle size={13} /> {result.message}
                    </span>
                  )}
                </div>
              </div>

              {/* 파일 슬롯 */}
              <div className="px-4 py-3 flex flex-col gap-2">
                {vendor.files.map((slot) => (
                  <CompactFileSlot
                    key={slot.key}
                    label={slot.label}
                    file={files[slot.key]}
                    onSelect={(f) => setFile(vendor.id, slot.key, f)}
                    disabled={processing}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* 하단 액션 */}
      <div className="sticky bottom-4 flex items-center gap-3">
        <button
          onClick={handleProcess}
          disabled={processing || readyVendors.length === 0}
          className="flex-1 flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700
            disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-semibold
            py-3.5 rounded-xl shadow-lg shadow-indigo-200 transition-all text-sm"
        >
          {processing ? (
            <><Loader2 size={16} className="animate-spin" /> 처리 중…</>
          ) : (
            <>
              <Package size={16} />
              {readyVendors.length > 0
                ? `${readyVendors.length}개 거래처 일괄 처리`
                : '파일을 올려주세요'}
            </>
          )}
        </button>

        {(allDone || Object.values(vendorFiles).some((vf) => Object.values(vf).some((f) => f != null))) && (
          <button
            onClick={handleClearAll}
            disabled={processing}
            className="px-4 py-3.5 rounded-xl border border-slate-200 text-slate-600
              hover:bg-slate-50 disabled:opacity-50 text-sm font-medium transition-colors"
          >
            초기화
          </button>
        )}
      </div>

      {/* 완료 요약 */}
      {allDone && (
        <div className={`mt-4 p-4 rounded-xl border text-sm font-medium
          ${errorCount === 0
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-amber-50 border-amber-200 text-amber-700'}`}
        >
          {errorCount === 0
            ? `✅ ${doneCount}개 거래처 처리 완료 — 파일이 다운로드되었습니다.`
            : `⚠️ ${doneCount}개 완료, ${errorCount}개 실패 — 실패한 거래처를 확인해주세요.`}
        </div>
      )}
    </div>
  );
}

export default BatchTrackingPage;
