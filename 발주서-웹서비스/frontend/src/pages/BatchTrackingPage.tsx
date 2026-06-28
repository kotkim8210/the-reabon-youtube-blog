import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Loader2, Package, XCircle } from 'lucide-react';

import { useUser } from '../App';
import { downloadBlob, mergeBatchTrackingResults, processFile } from '../api';
import { loadToolPrefs } from '../lib/toolCatalog';

interface FileSlot {
  key: string;
  label: string;
}

interface VendorConfig {
  id: string;
  toolId: string;
  preferenceIds: string[];
  label: string;
  icon: string;
  color: {
    border: string;
    header: string;
    badge: string;
  };
  files: FileSlot[];
}

interface VendorResult {
  status: 'idle' | 'processing' | 'done' | 'error';
  message?: string;
}

interface BatchSummary {
  tone: 'success' | 'warning' | 'error';
  message: string;
}

const VENDORS: VendorConfig[] = [
  {
    id: 'chamdureup',
    toolId: 'chamdureup-tracking',
    preferenceIds: ['chamdureup-unified'],
    label: '참두릅',
    icon: '🌱',
    color: {
      border: 'border-green-200',
      header: 'bg-green-50',
      badge: 'bg-green-100 text-green-700',
    },
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'myeongi',
    toolId: 'myeongi-tracking',
    preferenceIds: ['myeongi-unified'],
    label: '명이나물',
    icon: '🌿',
    color: {
      border: 'border-emerald-200',
      header: 'bg-emerald-50',
      badge: 'bg-emerald-100 text-emerald-700',
    },
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'kolrabi',
    toolId: 'tracking-input',
    preferenceIds: ['kolrabi-unified'],
    label: '콜라비·초당옥수수·미니밤호박 1kg',
    icon: '🥬',
    color: {
      border: 'border-blue-200',
      header: 'bg-blue-50',
      badge: 'bg-blue-100 text-blue-700',
    },
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'tomato',
    toolId: 'tomato-tracking',
    preferenceIds: ['tomato-unified'],
    label: '대저토마토·남해땅두릅·초당옥수수·신비복숭아',
    icon: '🍅🥒🌿',
    color: {
      border: 'border-red-200',
      header: 'bg-red-50',
      badge: 'bg-red-100 text-red-700',
    },
    files: [
      { key: 'tomato_reply', label: '제이비티 회신 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
  {
    id: 'gaegeolmu',
    toolId: 'gaegeolmu-tracking',
    preferenceIds: ['gaegeolmu-tracking'],
    label: '게걸무씨앗기름',
    icon: '🌾',
    color: {
      border: 'border-amber-200',
      header: 'bg-amber-50',
      badge: 'bg-amber-100 text-amber-700',
    },
    files: [
      { key: 'tracking', label: '택배발송 파일 (B=운송장, C=이름)' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
  },
];

function CompactFileSlot({
  label,
  file,
  onSelect,
  disabled,
}: {
  label: string;
  file: File | null;
  onSelect: (file: File | null) => void;
  disabled: boolean;
}) {
  const handleDrop = (event: React.DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    if (disabled) return;
    const nextFile = event.dataTransfer.files?.[0];
    if (nextFile) {
      onSelect(nextFile);
    }
  };

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    onSelect(nextFile);
    event.target.value = '';
  };

  return (
    <label
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors ${
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
      } ${
        file
          ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
          : 'border-dashed border-slate-300 bg-slate-50 text-slate-500 hover:border-indigo-300 hover:bg-indigo-50'
      }`}
      onDragOver={(event) => event.preventDefault()}
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
          <svg className="h-3.5 w-3.5 shrink-0 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <span className="max-w-[160px] truncate font-medium">{file.name}</span>
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              onSelect(null);
            }}
            className="ml-auto shrink-0 text-indigo-400 hover:text-red-500"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </>
      ) : (
        <>
          <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
          </svg>
          <span>{label}</span>
        </>
      )}
    </label>
  );
}

function BatchTrackingPage() {
  const { user } = useUser();
  const userId = user?.user_id ?? 'anon';
  const [prefsVersion, setPrefsVersion] = useState(0);
  const [vendorFiles, setVendorFiles] = useState<Record<string, Record<string, File | null>>>(
    () =>
      Object.fromEntries(
        VENDORS.map((vendor) => [
          vendor.id,
          Object.fromEntries(vendor.files.map((file) => [file.key, null])),
        ]),
      ),
  );
  const [results, setResults] = useState<Record<string, VendorResult>>(
    () => Object.fromEntries(VENDORS.map((vendor) => [vendor.id, { status: 'idle' }])),
  );
  const [processing, setProcessing] = useState(false);
  const [batchSummary, setBatchSummary] = useState<BatchSummary | null>(null);

  useEffect(() => {
    const refreshPrefs = () => setPrefsVersion((prev) => prev + 1);
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refreshPrefs();
      }
    };

    window.addEventListener('focus', refreshPrefs);
    window.addEventListener('storage', refreshPrefs);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.removeEventListener('focus', refreshPrefs);
      window.removeEventListener('storage', refreshPrefs);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, []);

  const visibleVendors = useMemo(() => {
    const prefs = loadToolPrefs(userId);
    return VENDORS.filter((vendor) =>
      vendor.preferenceIds.every(
        (preferenceId) =>
          !prefs.hidden.includes(preferenceId) && !prefs.deleted.includes(preferenceId),
      ),
    );
  }, [prefsVersion, userId]);

  const readyVendors = visibleVendors.filter((vendor) =>
    vendor.files.every((file) => vendorFiles[vendor.id]?.[file.key] != null),
  );

  const setFile = (vendorId: string, fileKey: string, file: File | null) => {
    setVendorFiles((prev) => ({
      ...prev,
      [vendorId]: {
        ...prev[vendorId],
        [fileKey]: file,
      },
    }));
    setBatchSummary(null);
    setResults((prev) => ({
      ...prev,
      [vendorId]: { status: 'idle' },
    }));
  };

  const handleProcess = async () => {
    if (readyVendors.length === 0) return;

    setProcessing(true);
    setBatchSummary(null);

    const successfulOutputs: Array<{ blob: Blob; filename: string }> = [];

    for (const vendor of readyVendors) {
      setResults((prev) => ({
        ...prev,
        [vendor.id]: { status: 'processing' },
      }));

      try {
        const files = Object.fromEntries(
          Object.entries(vendorFiles[vendor.id]).filter(([, file]) => file != null),
        ) as Record<string, File>;

        const result = await processFile(vendor.toolId, files);
        successfulOutputs.push({ blob: result.blob, filename: result.filename });

        const stats = result.stats;
        const message = stats
          ? `${stats.filled ?? stats.success ?? 0}건 처리 완료`
          : '처리 완료';

        setResults((prev) => ({
          ...prev,
          [vendor.id]: { status: 'done', message },
        }));
      } catch (error) {
        const message = error instanceof Error ? error.message : '처리에 실패했습니다.';
        setResults((prev) => ({
          ...prev,
          [vendor.id]: { status: 'error', message },
        }));
      }
    }

    if (successfulOutputs.length > 0) {
      try {
        const mergedResult = await mergeBatchTrackingResults(successfulOutputs);
        downloadBlob(mergedResult.blob, mergedResult.filename);

        const mergedRows = Number(mergedResult.stats?.merged_rows ?? 0);
        const successCount = successfulOutputs.length;
        const failCount = readyVendors.length - successCount;

        setBatchSummary({
          tone: failCount === 0 ? 'success' : 'warning',
          message:
            failCount === 0
              ? `통합 송장입력 파일 1개를 다운로드했습니다. (${mergedRows}행)`
              : `${successCount}개 거래처를 통합 파일 1개로 출력했습니다. ${failCount}개 거래처는 실패 내역을 확인해주세요.`,
        });
      } catch (error) {
        successfulOutputs.forEach((file) => downloadBlob(file.blob, file.filename));
        const message = error instanceof Error ? error.message : '통합 파일 생성 실패';
        setBatchSummary({
          tone: 'warning',
          message: `통합 파일 생성에 실패해 개별 결과 파일로 내려받았습니다. ${message}`,
        });
      }
    } else {
      setBatchSummary({
        tone: 'error',
        message: '완료된 거래처가 없어 통합 파일을 만들지 못했습니다.',
      });
    }

    setProcessing(false);
  };

  const handleClearAll = () => {
    setVendorFiles(
      Object.fromEntries(
        VENDORS.map((vendor) => [
          vendor.id,
          Object.fromEntries(vendor.files.map((file) => [file.key, null])),
        ]),
      ),
    );
    setResults(
      Object.fromEntries(VENDORS.map((vendor) => [vendor.id, { status: 'idle' }])),
    );
    setBatchSummary(null);
  };

  const doneCount = Object.values(results).filter((result) => result.status === 'done').length;
  const errorCount = Object.values(results).filter((result) => result.status === 'error').length;
  const allDone =
    !processing &&
    readyVendors.length > 0 &&
    doneCount + errorCount === readyVendors.length &&
    doneCount + errorCount > 0;

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6">
        <div className="mb-1 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 shadow-sm">
            <Package size={20} className="text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-800">일괄 운송장 입력</h2>
            <p className="text-sm text-slate-500">
              거래처별 파일을 올리면 한 번에 처리합니다. 마지막에는 통합 송장입력 파일 1개로 내려받습니다.
            </p>
          </div>
        </div>
      </div>

      <div className="mb-6 rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
        처리할 거래처의 파일만 올려주세요. 파일이 없는 거래처는 자동으로 건너뜁니다.
      </div>

      <div className="mb-6 flex flex-col gap-4">
        {visibleVendors.map((vendor) => {
          const result = results[vendor.id];
          const files = vendorFiles[vendor.id];
          const isReady = vendor.files.every((file) => files[file.key] != null);
          const isProcessing = result.status === 'processing';
          const isDone = result.status === 'done';
          const isError = result.status === 'error';

          return (
            <div
              key={vendor.id}
              className={`overflow-hidden rounded-2xl border bg-white shadow-sm ${vendor.color.border} ${
                isDone ? 'opacity-75' : ''
              }`}
            >
              <div className={`flex items-center justify-between px-4 py-3 ${vendor.color.header}`}>
                <div className="flex items-center gap-2">
                  <span className="text-lg leading-none">{vendor.icon}</span>
                  <span className="text-sm font-semibold text-slate-800">{vendor.label}</span>
                  {isReady && result.status === 'idle' && (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${vendor.color.badge}`}>
                      준비됨
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  {isProcessing && (
                    <span className="flex items-center gap-1 text-xs font-medium text-indigo-600">
                      <Loader2 size={13} className="animate-spin" />
                      처리 중
                    </span>
                  )}
                  {isDone && (
                    <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
                      <CheckCircle2 size={13} />
                      {result.message}
                    </span>
                  )}
                  {isError && (
                    <span className="flex items-center gap-1 text-xs font-medium text-red-600">
                      <XCircle size={13} />
                      {result.message}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex flex-col gap-2 px-4 py-3">
                {vendor.files.map((slot) => (
                  <CompactFileSlot
                    key={slot.key}
                    label={slot.label}
                    file={files[slot.key]}
                    onSelect={(file) => setFile(vendor.id, slot.key, file)}
                    disabled={processing}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="sticky bottom-4 flex items-center gap-3">
        <button
          onClick={handleProcess}
          disabled={processing || readyVendors.length === 0}
          className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 py-3.5 text-sm font-semibold text-white shadow-lg shadow-indigo-200 transition-all hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {processing ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              처리 중
            </>
          ) : (
            <>
              <Package size={16} />
              {readyVendors.length > 0
                ? `${readyVendors.length}개 거래처 처리 후 통합 파일 출력`
                : '파일을 올려주세요'}
            </>
          )}
        </button>

        {(allDone ||
          Object.values(vendorFiles).some((vendor) =>
            Object.values(vendor).some((file) => file != null),
          )) && (
          <button
            onClick={handleClearAll}
            disabled={processing}
            className="rounded-xl border border-slate-200 px-4 py-3.5 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50"
          >
            초기화
          </button>
        )}
      </div>

      {visibleVendors.length === 0 && (
        <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-6 text-center text-sm text-slate-500">
          표시할 거래처가 없습니다. 도구 설정에서 숨김 상태를 확인해주세요.
        </div>
      )}

      {allDone && batchSummary && (
        <div
          className={`mt-4 rounded-xl border p-4 text-sm font-medium ${
            batchSummary.tone === 'success'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : batchSummary.tone === 'warning'
                ? 'border-amber-200 bg-amber-50 text-amber-700'
                : 'border-red-200 bg-red-50 text-red-700'
          }`}
        >
          {batchSummary.message}
        </div>
      )}
    </div>
  );
}

export default BatchTrackingPage;
