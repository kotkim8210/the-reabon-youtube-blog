import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Pencil, Check, X } from 'lucide-react';
import FileUpload from '../components/FileUpload';
import {
  processFile, downloadBlob, ProcessResult, processTossWatermelonTracking, processDaangnOrder,
  fetchSabangStatus, testSabangConnection, processSabangFruitOrder, processSabangFruitTracking,
  fetchSabangCourierCodes, SabangCourierCode,
  SabangStatus, SabangTrackingResult,
} from '../api';
import { useUser } from '../App';
import { loadToolPrefs, setSectionTitle } from '../lib/toolCatalog';
import { getDefaultGogumaDateRange } from '../lib/gogumaDateRange';

// ── 인라인 편집 가능한 제목 ───────────────────────────────────────
function EditableTitle({
  value,
  onSave,
  className = '',
}: {
  value: string;
  onSave: (next: string) => void;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    setDraft(value);
  }, [value]);

  const commit = () => {
    onSave(draft.trim());
    setEditing(false);
  };
  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  if (editing) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <input
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') cancel();
          }}
          className="rounded-lg border border-indigo-300 px-2 py-1 text-sm font-bold text-gray-900
                     outline-none focus:ring-2 focus:ring-indigo-200 min-w-[12rem]"
        />
        <button onClick={commit} title="저장" className="text-green-600 hover:text-green-700">
          <Check size={16} />
        </button>
        <button onClick={cancel} title="취소" className="text-gray-400 hover:text-gray-600">
          <X size={16} />
        </button>
      </span>
    );
  }

  return (
    <span className={`group inline-flex items-center gap-1.5 ${className}`}>
      {value}
      <button
        onClick={() => setEditing(true)}
        title="제목 수정 (비우고 저장하면 기본값 복원)"
        className="text-gray-300 hover:text-indigo-500 opacity-60 group-hover:opacity-100 transition"
      >
        <Pencil size={14} />
      </button>
    </span>
  );
}

// ── 타입 ──────────────────────────────────────────────────────────
interface FileConfig { key: string; label: string; accept?: string; acceptLabel?: string; }

interface SectionConfig {
  title: string;
  icon: string;
  apiToolId: string;
  files: FileConfig[];
  buttonLabel: string;
  tossDateRange?: boolean;
  tossDateTitle?: string;
  tossDateHint?: string;
  tossDefaultDays?: number;  // 기본 수집 기간(며칠 전부터). 0=오늘만, 1=2일(어제~오늘)
}

interface ProductConfig {
  title: string;
  description: string;
  icon: string;
  bgClass: string;
  order: SectionConfig;
  tracking: SectionConfig;
  event?: SectionConfig;
}

// ── 제품별 설정 ───────────────────────────────────────────────────
const productConfigs: Record<string, ProductConfig> = {
  chamdureup: {
    title: '참두릅',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🌱',
    bgClass: 'bg-green-50',
    order: {
      title: '발주서 생성',
      icon: '📋',
      apiToolId: 'chamdureup-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
      buttonLabel: '발주서 생성',
    },
    tracking: {
      title: '운송장번호 입력',
      icon: '📦',
      apiToolId: 'chamdureup-tracking',
      files: [
        { key: 'orderlist', label: 'Orderlist 파일' },
        { key: 'delivery', label: 'DeliveryList 파일' },
      ],
      buttonLabel: '운송장 입력',
    },
  },
  kolrabi: {
    title: '콜라비·미니밤호박 1kg·홍감자·백도딱딱이복숭아 2·4kg(제주다팜)',
    description: '취급품목: 콜라비·미니밤호박(보우짱 로얄과) 1kg·홍감자·백도딱딱이복숭아 2·4kg 제주다팜 발주서 생성 + 운송장번호 입력 · 홍감자 매칭: 중 1kg→중 2kg, 대 3kg→특 3kg, 대 5kg→특 5kg (2026-07 쥬얼리 품절로 이관) · 백도딱딱이복숭아 중과·대과 2·4kg → 발주명 "딱딱이 복숭아 {등급} {kg}kg" (2026-07 쥬얼리→제주다팜 이관, 1kg은 명이(쥬얼리) 메뉴 잔류) · 미니밤호박 3·5·10kg과 초당옥수수·애플초당옥수수·성주참외는 명이나물(쥬얼리) 메뉴',
    icon: '🥬',
    bgClass: 'bg-green-50',
    order: {
      title: '콜라비·미니밤호박 1kg·홍감자·백도딱딱이복숭아 2·4kg 발주서 생성',
      icon: '📋',
      apiToolId: 'kolrabi-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
      buttonLabel: '발주서 생성',
      tossDateRange: true,
      tossDefaultDays: 1,
      tossDateTitle: '토스 주문 수집 (제주다팜 콜라비·미니밤호박·홍감자·백도딱딱이복숭아 2·4kg)',
      tossDateHint: '기본 2일(어제~오늘) 토스 콜라비·미니밤호박 1kg·홍감자·백도딱딱이복숭아 2·4kg 주문을 제주다팜 발주서에 합칩니다. 미니밤호박 3·5·10kg과 백도 1kg은 명이(쥬얼리) 메뉴. 배송중·송장입력 건은 자동 제외. (추가발주는 "오늘", 안 합치려면 "수집안함")',
    },
    tracking: {
      title: '콜라비·미니밤호박 1kg·홍감자·백도딱딱이복숭아 2·4kg 운송장번호 입력',
      icon: '📦',
      apiToolId: 'tracking-input',
      files: [
        { key: 'orderlist', label: 'Orderlist 파일' },
        { key: 'delivery', label: 'DeliveryList 파일' },
      ],
      buttonLabel: '운송장 입력',
    },
  },
  myeongi: {
    title: '명이나물+애플초당옥수수+초당옥수수+망고수박+수박+성주참외+신비복숭아+미니밤호박+거반도납작복숭아+대극천복숭아+백도딱딱이복숭아',
    description: '쥬얼리프룻 발주서 생성 + 운송장번호 입력 · 취급품목: 명이나물·애플초당옥수수·초당옥수수·망고수박·수박·성주참외·신비복숭아·미니밤호박(보우짱 로얄과 3·5·10kg, 1kg은 제주다팜 메뉴)·거반도 납작복숭아(500g·1kg·2kg)·대극천 복숭아(소과 1kg)·백도 딱딱이복숭아(중과·대과 1kg만; 2·4kg은 콜라비(제주다팜) 메뉴로 이관) · 홍감자는 2026-07부터 콜라비(제주다팜) 메뉴로 이관',
    icon: '🌿',
    bgClass: 'bg-green-50',
    order: {
      title: '명이나물+애플초당옥수수+초당옥수수+망고수박+수박+성주참외+신비복숭아+미니밤호박+거반도납작복숭아+대극천복숭아+백도딱딱이복숭아 발주서 생성',
      icon: '📋',
      apiToolId: 'myeongi-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일 (쿠팡)' }],
      buttonLabel: '발주서 생성',
      tossDateRange: true,
      tossDefaultDays: 1,  // 기본 2일(어제~오늘). '오늘' 버튼은 추가발주용으로 유지
      tossDateTitle: '토스 주문 수집 (쥬얼리)',
      tossDateHint: '기본 2일(어제~오늘) 토스 주문(수박·성주참외·신비복숭아 1·2kg·망고수박·백도딱딱이복숭아 1kg)을 쥬얼리프룻 발주서에 합칩니다. 백도 2·4kg과 홍감자는 콜라비(제주다팜) 메뉴. 신비복숭아 3·4kg은 제이비티 메뉴로. 배송중·송장입력 건은 자동 제외. (추가발주는 "오늘", 안 합치려면 "수집안함")',
    },
    tracking: {
      title: '명이나물+애플초당옥수수+초당옥수수+망고수박+수박+성주참외+신비복숭아+미니밤호박+거반도납작복숭아+대극천복숭아+백도딱딱이복숭아 운송장번호 입력',
      icon: '📦',
      apiToolId: 'myeongi-tracking',
      files: [
        { key: 'orderlist', label: 'Orderlist 파일' },
        { key: 'delivery', label: 'DeliveryList 파일' },
      ],
      buttonLabel: '운송장 입력',
    },
    event: {
      title: '라이브 이벤트 당첨자 발주서 생성 (참외·신비/거반도/대극천/백도딱딱이 복숭아)',
      icon: '🎉',
      apiToolId: 'event-winner-order',
      files: [
        { key: 'winners', label: '라이브 이벤트 당첨자 CSV (winners_raw)', accept: '.csv', acceptLabel: '.csv 파일' },
      ],
      buttonLabel: '이벤트 발주서 생성',
    },
  },
  tomato: {
    title: '대저토마토·남해땅두릅·신비복숭아',
    description: '발주서 생성 + 운송장번호 입력 · 초당옥수수는 콜라비(제주다팜) 메뉴로 이동',
    icon: '🍅',
    bgClass: 'bg-red-50',
    order: {
      title: '발주서 생성',
      icon: '📋',
      apiToolId: 'tomato-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일 (쿠팡)' }],
      buttonLabel: '발주서 생성',
      tossDateRange: true,
      tossDefaultDays: 1,  // 기본 2일(어제~오늘). '오늘' 버튼은 추가발주용
      tossDateTitle: '토스 신비복숭아 3·4kg 주문 수집',
      tossDateHint: '기본 2일(어제~오늘) 토스 신비복숭아 3·4kg 주문을 제이비티 발주서에 합칩니다. 배송중·송장입력된 건은 자동 제외. (1·2kg은 명이(쥬얼리) 메뉴 / 수집안함 = DeliveryList만)',
    },
    tracking: {
      title: '대저토마토·남해땅두릅·신비복숭아 운송장번호 입력',
      icon: '📦',
      apiToolId: 'tomato-tracking',
      files: [
        { key: 'tomato_reply', label: '제이비티 회신 파일' },
        { key: 'delivery', label: 'DeliveryList 파일' },
      ],
      buttonLabel: '운송장 입력',
    },
  },
};

// ── 통계 포맷 ─────────────────────────────────────────────────────
function formatStats(stats: Record<string, unknown>): string[] {
  const labels: Record<string, string> = {
    duplicate_skipped: '이전 발주분 제외',
    duplicate_skipped_names: '제외된 주문(받는분)',
  };
  return Object.entries(stats).map(([key, value]) =>
    typeof value === 'number' ? `${labels[key] || key}: ${value}건` : `${labels[key] || key}: ${value}`
  );
}

function localDateString(offsetDays = 0): string {
  const current = new Date();
  current.setDate(current.getDate() + offsetDays);
  const localTime = current.getTime() - current.getTimezoneOffset() * 60 * 1000;
  return new Date(localTime).toISOString().slice(0, 10);
}

// ── 섹션 컴포넌트 ─────────────────────────────────────────────────
function ProcessSection({
  section,
  title,
  onTitleSave,
}: {
  section: SectionConfig;
  title: string;
  onTitleSave: (next: string) => void;
}) {
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [extraValues, setExtraValues] = useState<Record<string, string>>(() => {
    // 발주 섹션은 '이전 발주분 자동 제외(중복발주 방지)' 기본 ON
    const init: Record<string, string> = section.apiToolId.endsWith('-order') ? { exclude_issued: 'true' } : {};
    if (!section.tossDateRange) return init;
    // 요일 자동 선택(고구마와 동일): 월요일=4일(금~월), 공휴일 다음날=3일.
    // 섹션 기본값(tossDefaultDays)보다 길 때만 요일 규칙을 우선 — 월요일 실수 방지.
    const auto = getDefaultGogumaDateRange();
    const days = Math.max(auto.days, (section.tossDefaultDays ?? 0) + 1);
    return { ...init, toss_from_date: localDateString(-(days - 1)), toss_to_date: localDateString() };
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState('');

  const allUploaded = section.files.every((f) => files[f.key] != null);

  const handleFileSelect = (key: string) => (file: File) => {
    setFiles((prev) => ({ ...prev, [key]: file || null }));
    setResult(null);
    setError('');
  };

  const handleProcess = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const fileMap: Record<string, File> = {};
      for (const [k, f] of Object.entries(files)) {
        if (f) fileMap[k] = f;
      }
      const res = await processFile(section.apiToolId, fileMap, extraValues);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : '처리 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFiles({});
    setResult(null);
    setError('');
  };

  const hasAny = Object.keys(files).length > 0 || !!result || !!error;

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4">
      {/* 섹션 헤더 */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-gray-50 rounded-xl flex items-center justify-center text-xl">
          {section.icon}
        </div>
        <h3 className="text-base font-bold text-gray-900">
          <EditableTitle value={title} onSave={onTitleSave} />
        </h3>
      </div>

      {/* 파일 업로드 */}
      <div className="space-y-4">
        {section.files.map((f) => (
          <FileUpload
            key={f.key}
            label={f.label}
            accept={f.accept}
            acceptLabel={f.acceptLabel}
            file={files[f.key] || null}
            onFileSelect={handleFileSelect(f.key)}
          />
        ))}
      </div>

      {section.tossDateRange && (
        <div className="rounded-xl border border-orange-200 bg-orange-50/70 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-bold text-gray-900">{section.tossDateTitle || '토스 주문 수집'}</p>
              <p className="mt-0.5 text-xs text-gray-500">{section.tossDateHint || '날짜가 있으면 토스 API 주문을 제이비티 발주서에 합칩니다.'}</p>
            </div>
            <div className="flex gap-1.5">
              {[
                { label: '오늘', days: 0 },
                { label: '2일', days: 1 },
                { label: '3일', days: 2 },
                { label: '4일', days: 3 },
                { label: '수집안함', days: -1 },
              ].map((preset) => {
                const isActive = preset.days >= 0
                  ? extraValues.toss_from_date === localDateString(-preset.days)
                    && extraValues.toss_to_date === localDateString()
                  : !extraValues.toss_from_date && !extraValues.toss_to_date;
                return (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => {
                    if (preset.days < 0) {
                      setExtraValues((prev) => ({ ...prev, toss_from_date: '', toss_to_date: '' }));
                      return;
                    }
                    setExtraValues((prev) => ({
                      ...prev,
                      toss_from_date: localDateString(-preset.days),
                      toss_to_date: localDateString(),
                    }));
                  }}
                  className={`rounded-lg border px-2 py-1 text-xs font-semibold transition ${
                    isActive
                      ? 'border-orange-500 bg-orange-500 text-white shadow-sm'
                      : 'border-orange-300 text-orange-700 hover:bg-orange-100'
                  }`}
                >
                  {preset.label}
                </button>
                );
              })}
            </div>
          </div>
          <p className="mb-2 text-[11px] font-medium text-orange-600">
            ⏰ 월요일엔 자동으로 4일(금~월), 공휴일 다음날엔 3일로 시작합니다. 다르게 수집하려면 위 버튼으로 바꾸세요.
          </p>
          <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-500">시작일</span>
              <input
                type="date"
                value={extraValues.toss_from_date || ''}
                onChange={(event) => setExtraValues((prev) => ({ ...prev, toss_from_date: event.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-orange-400 focus:ring-2 focus:ring-orange-200"
              />
            </label>
            <span className="hidden pb-2 text-gray-400 sm:block">~</span>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-gray-500">종료일</span>
              <input
                type="date"
                value={extraValues.toss_to_date || ''}
                onChange={(event) => setExtraValues((prev) => ({ ...prev, toss_to_date: event.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-orange-400 focus:ring-2 focus:ring-orange-200"
              />
            </label>
          </div>
        </div>
      )}

      {/* 버튼 */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleProcess}
          disabled={!allUploaded || loading}
          className="bg-indigo-600 text-white px-5 py-2.5 rounded-xl font-semibold text-sm
                     hover:bg-indigo-700 active:bg-indigo-800
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-all duration-200 flex items-center gap-2"
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
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              {section.buttonLabel}
            </>
          )}
        </button>
        {hasAny && (
          <button
            onClick={handleReset}
            disabled={loading}
            className="text-gray-500 hover:text-gray-700 px-4 py-2.5 rounded-xl
                       font-medium text-sm hover:bg-gray-100
                       disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            초기화
          </button>
        )}
      </div>

      {section.apiToolId.endsWith('-order') && (
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={extraValues.exclude_issued !== 'false'}
            onChange={(e) =>
              setExtraValues((prev) => ({ ...prev, exclude_issued: e.target.checked ? 'true' : 'false' }))
            }
            className="w-4 h-4 accent-indigo-600"
          />
          <span>
            <span className="font-semibold">이전 발주분 자동 제외</span>
            <span className="ml-1 text-xs text-gray-400">
              직전 영업일까지 발주서에 넣은 주문은 건너뜀 (같은 날 재생성은 그대로)
            </span>
          </span>
        </label>
      )}

      {/* 에러 */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 animate-fade-in">
          <div className="flex items-start gap-2">
            <svg className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.07 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <p className="text-sm text-red-600">{error}</p>
          </div>
        </div>
      )}

      {/* 성공 */}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 animate-fade-in">
          <p className="text-sm font-bold text-green-800 mb-2">처리 완료</p>
          {result.stats && (
            <div className="space-y-0.5 mb-3">
              {formatStats(result.stats).map((line, i) => (
                <p key={i} className="text-sm text-green-700">{line}</p>
              ))}
            </div>
          )}
          <button
            onClick={() => downloadBlob(result.blob, result.filename)}
            className="inline-flex items-center gap-2 bg-green-600 text-white
                       px-4 py-2 rounded-xl font-semibold text-sm
                       hover:bg-green-700 transition-all shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            {result.filename} 다운로드
          </button>
        </div>
      )}
    </div>
  );
}

// ── 토스 운송장 자동등록(API) 카드 (고구마식) ──────────────────────
function TossApiTrackingCard({ supplierLabel = '쥬얼리' }: { supplierLabel?: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');

  const run = async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await processTossWatermelonTracking(file);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : '토스 운송장 등록 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center text-xl">📦</div>
        <div>
          <h3 className="text-base font-bold text-gray-900">토스 운송장 자동등록 (API)</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {supplierLabel} 거래처 회신(orderlist) 파일을 올리면 토스 주문에 운송장번호를 토스 API로 자동 등록합니다.
            결제완료 주문은 상품준비중으로 자동 전환됩니다.
          </p>
          <p className="text-xs font-semibold text-amber-700 mt-1">
            ⚠️ DeliveryList(쿠팡 송장입력본)가 아니라, 토스 고객 송장이 들어있는 <b>거래처 회신(orderlist)</b> 파일을 올려야 합니다.
          </p>
        </div>
      </div>

      <FileUpload
        label={`${supplierLabel} 거래처 회신(orderlist) 파일`}
        file={file}
        onFileSelect={(f) => {
          setFile(f || null);
          setResult(null);
          setError('');
        }}
      />

      <div className="flex items-center gap-3">
        <button
          onClick={run}
          disabled={!file || loading}
          className="bg-blue-600 text-white px-5 py-2.5 rounded-xl font-semibold text-sm
                     hover:bg-blue-700 active:bg-blue-800
                     disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2"
        >
          {loading ? '등록 중...' : '토스 운송장 등록'}
        </button>
        {(file || result || error) && (
          <button
            onClick={() => { setFile(null); setResult(null); setError(''); }}
            disabled={loading}
            className="text-gray-500 hover:text-gray-700 px-4 py-2.5 rounded-xl font-medium text-sm hover:bg-gray-100 transition-all"
          >
            초기화
          </button>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4">
          <p className="text-sm font-bold text-green-800 mb-2">토스 운송장 등록 결과</p>
          <div className="space-y-0.5">
            {formatStats(result).map((line, i) => (
              <p key={i} className="text-sm text-green-700">{line}</p>
            ))}
          </div>
          {Number((result.toss_success as number) ?? 0) === 0 && (
            <p className="mt-2 text-xs text-amber-700">
              성공 0건이면 올린 파일이 DeliveryList(쿠팡)일 수 있어요. 토스 고객이 포함된 <b>{supplierLabel} 회신(orderlist)</b> 파일인지 확인하세요.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── 당근마켓 주문 발주 카드 (텍스트 붙여넣기) ─────────────────────
function DaangnOrderCard() {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState('');

  const run = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await processDaangnOrder(text);
      setResult(res);
      downloadBlob(res.blob, res.filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : '당근 발주 처리 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-orange-50 rounded-xl flex items-center justify-center text-xl">🥕</div>
        <div>
          <h3 className="text-base font-bold text-gray-900">당근마켓 주문 발주 (붙여넣기)</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            당근 <b>주문 상세</b> 화면 내용을 복사해 붙여넣으면 쥬얼리프룻 발주서로 변환·다운로드합니다.
            여러 건은 '주문 상세' 단위로 이어붙여 한 번에 처리할 수 있습니다. (예: 대극천 복숭아)
          </p>
        </div>
      </div>

      <textarea
        value={text}
        onChange={(e) => { setText(e.target.value); setResult(null); setError(''); }}
        placeholder={'당근 주문 상세 텍스트를 붙여넣으세요.\n예) 대극천 복숭아 / 대과 2kg 1개 / 받는 사람 ... / 배송지 ... / 연락처 ...'}
        rows={8}
        className="w-full rounded-xl border border-gray-200 p-3 text-sm font-mono leading-5
                   focus:outline-none focus:ring-2 focus:ring-orange-300 resize-y"
      />

      <div className="flex items-center gap-3">
        <button
          onClick={run}
          disabled={!text.trim() || loading}
          className="bg-orange-500 text-white px-5 py-2.5 rounded-xl font-semibold text-sm
                     hover:bg-orange-600 active:bg-orange-700
                     disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2"
        >
          {loading ? '생성 중...' : '발주서 생성'}
        </button>
        {(text || result || error) && (
          <button
            onClick={() => { setText(''); setResult(null); setError(''); }}
            disabled={loading}
            className="text-gray-500 hover:text-gray-700 px-4 py-2.5 rounded-xl font-medium text-sm hover:bg-gray-100 transition-all"
          >
            초기화
          </button>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4">
          <p className="text-sm font-bold text-green-800 mb-2">당근 발주서 생성 완료 (자동 다운로드됨)</p>
          {result.stats && (
            <div className="space-y-0.5 mb-3">
              {formatStats(result.stats).map((line, i) => (
                <p key={i} className="text-sm text-green-700">{line}</p>
              ))}
            </div>
          )}
          <button
            onClick={() => downloadBlob(result.blob, result.filename)}
            className="inline-flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-xl font-semibold text-sm hover:bg-green-700 transition-all"
          >
            다시 다운로드
          </button>
        </div>
      )}
    </div>
  );
}

// ── 사방넷 카드 숨기기 래퍼 (localStorage에 유지) ──────────────────
function SabangHideWrap({ storageKey, title, children }: {
  storageKey: string;
  title: string;
  children: (onHide: () => void) => JSX.Element;
}) {
  const [hidden, setHidden] = useState(() => localStorage.getItem(storageKey) === '1');
  useEffect(() => {
    setHidden(localStorage.getItem(storageKey) === '1');
  }, [storageKey]);
  const hide = () => { localStorage.setItem(storageKey, '1'); setHidden(true); };
  const show = () => { localStorage.setItem(storageKey, '0'); setHidden(false); };

  if (hidden) {
    return (
      <div className="bg-white/60 border border-dashed border-gray-300 rounded-2xl px-5 py-3 flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-400">🔄 {title} — 숨겨져 있습니다</span>
        <button onClick={show}
          className="text-xs font-bold text-purple-600 hover:text-purple-700 transition">
          보이기
        </button>
      </div>
    );
  }
  return children(hide);
}

// ── 사방넷 주문 자동수집 → 발주서 (과일/Itsoft) ────────────────────
function SabangOrderCard({ section, supplierLabel, onHide }: {
  section: 'myeongi' | 'kolrabi';
  supplierLabel: string;
  onHide?: () => void;
}) {
  const [status, setStatus] = useState<SabangStatus | null>(null);
  const [fromDate, setFromDate] = useState(() => {
    const auto = getDefaultGogumaDateRange();
    return localDateString(-(auto.days - 1));
  });
  const [toDate, setToDate] = useState(localDateString());
  const [mergeToss, setMergeToss] = useState(true);
  const [excludeIssued, setExcludeIssued] = useState(true);
  const [loading, setLoading] = useState(false);
  const [testMsg, setTestMsg] = useState('');
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchSabangStatus().then(setStatus).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await processSabangFruitOrder(section, {
        fromDate,
        toDate,
        tossFromDate: mergeToss ? fromDate : '',
        tossToDate: mergeToss ? toDate : '',
        excludeIssued,
      });
      setResult(res);
      downloadBlob(res.blob, res.filename);
    } catch (e) {
      setError(e instanceof Error ? e.message : '사방넷 수집 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const runTest = async () => {
    setTestMsg('확인 중...');
    try {
      const res = await testSabangConnection();
      setTestMsg(res.status === 'ok' ? `✅ ${res.message}` : `❌ ${res.message}`);
    } catch (e) {
      setTestMsg(`❌ ${e instanceof Error ? e.message : '연결 실패'}`);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-purple-200 p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-purple-50 rounded-xl flex items-center justify-center text-xl">🔄</div>
          <div>
            <h3 className="text-base font-bold text-gray-900">사방넷 주문 자동수집 → {supplierLabel} 발주서</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              쿠팡 Itsoft(과일) 주문을 사방넷 API로 끌어와 DeliveryList 업로드 없이 바로 발주서를 만듭니다.
              생성 즉시 자동 다운로드됩니다.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button onClick={runTest}
            className="px-3 py-1.5 rounded-lg border border-purple-200 text-xs font-semibold text-purple-700 hover:bg-purple-50 transition">
            연결 테스트
          </button>
          {onHide && (
            <button onClick={onHide} title="이 카드를 숨깁니다 (언제든 보이기로 복원)"
              className="px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-semibold text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition">
              숨기기
            </button>
          )}
        </div>
      </div>

      {status && !status.configured && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          ⚠️ 사방넷 연동키 미설정 — 사방넷 <b>마이페이지 &gt; 서비스 관리 &gt; 연동키 관리</b>에서 인증키 발급(유료 API 서비스) 후
          <code className="mx-1 rounded bg-amber-100 px-1">fly secrets set SABANG_COMPANY_ID=로그인ID SABANG_AUTH_KEY=인증키</code>
          설정이 필요합니다.
        </div>
      )}
      {testMsg && <p className="text-xs font-semibold text-gray-700">{testMsg}</p>}

      <div className="flex gap-1.5">
        {[
          { label: '오늘', days: 0 },
          { label: '2일', days: 1 },
          { label: '3일', days: 2 },
          { label: '4일', days: 3 },
        ].map((preset) => {
          const isActive = fromDate === localDateString(-preset.days) && toDate === localDateString();
          return (
            <button key={preset.label} type="button"
              onClick={() => { setFromDate(localDateString(-preset.days)); setToDate(localDateString()); setResult(null); }}
              className={`rounded-lg border px-2.5 py-1 text-xs font-semibold transition ${
                isActive
                  ? 'border-purple-500 bg-purple-500 text-white shadow-sm'
                  : 'border-purple-300 text-purple-700 hover:bg-purple-100'
              }`}>
              {preset.label}
            </button>
          );
        })}
      </div>

      <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-500">시작일</span>
          <input type="date" value={fromDate} onChange={(e) => { setFromDate(e.target.value); setResult(null); }}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-200" />
        </label>
        <span className="hidden pb-2 text-gray-400 sm:block">~</span>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-gray-500">종료일</span>
          <input type="date" value={toDate} onChange={(e) => { setToDate(e.target.value); setResult(null); }}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-200" />
        </label>
      </div>

      <div className="flex flex-wrap gap-4">
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input type="checkbox" checked={mergeToss} onChange={(e) => setMergeToss(e.target.checked)}
            className="w-4 h-4 accent-purple-600" />
          토스 주문도 같은 기간으로 합치기
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
          <input type="checkbox" checked={excludeIssued} onChange={(e) => setExcludeIssued(e.target.checked)}
            className="w-4 h-4 accent-purple-600" />
          이전 발주분 자동 제외
        </label>
      </div>

      <div>
        <button onClick={run} disabled={loading || !fromDate || !toDate}
          className="bg-purple-600 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-purple-700
                     disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2">
          {loading ? '사방넷에서 수집 중...' : '사방넷 수집 → 발주서 생성'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4">
          <p className="text-sm font-bold text-green-800 mb-2">발주서 생성 완료 (자동 다운로드됨)</p>
          {result.stats && (
            <div className="space-y-0.5 mb-3">
              {formatStats(result.stats).map((line, i) => (
                <p key={i} className="text-sm text-green-700">{line}</p>
              ))}
            </div>
          )}
          <button onClick={() => downloadBlob(result.blob, result.filename)}
            className="inline-flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-xl font-semibold text-sm hover:bg-green-700 transition-all">
            {result.filename} 다시 다운로드
          </button>
        </div>
      )}
    </div>
  );
}

// ── 사방넷 송장 자동전송 (orderlist 업로드) ────────────────────────
function SabangTrackingCard({ supplierLabel, onHide }: { supplierLabel: string; onHide?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  // 발주처마다 택배사가 다름(쥬얼리·제주다팜 기본 롯데, CJ대한통운인 곳도 있음) — 전송 시마다 선택
  const [courier, setCourier] = useState<'lotte' | 'cj' | 'custom'>('lotte');
  const [customCode, setCustomCode] = useState('');
  const [status, setStatus] = useState<SabangStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SabangTrackingResult | null>(null);
  const [error, setError] = useState('');
  const [detecting, setDetecting] = useState(false);
  const [detected, setDetected] = useState<SabangCourierCode[] | null>(null);
  const [detectMsg, setDetectMsg] = useState('');

  useEffect(() => {
    fetchSabangStatus().then(setStatus).catch(() => {});
  }, []);

  const detectCodes = async () => {
    setDetecting(true);
    setDetectMsg('');
    setDetected(null);
    try {
      const res = await fetchSabangCourierCodes(14);
      setDetected(res.codes);
      setDetectMsg(res.codes.length
        ? `최근 14일 출고완료 ${res.total_orders}건에서 코드 ${res.codes.length}종 발견 — 클릭하면 그 코드로 전송합니다.`
        : `최근 14일 출고완료 주문(${res.total_orders}건)에 택배사 코드가 없습니다.`);
    } catch (e) {
      setDetectMsg(`❌ ${e instanceof Error ? e.message : '자동 인식 실패'}`);
    } finally {
      setDetecting(false);
    }
  };

  const COURIERS = [
    { id: 'lotte' as const, label: '롯데택배', code: status?.tak_code_lotte || '' },
    { id: 'cj' as const, label: 'CJ대한통운', code: status?.tak_code_cj || '' },
    { id: 'custom' as const, label: '직접입력', code: customCode.trim() },
  ];
  const selected = COURIERS.find((c) => c.id === courier)!;
  const resolvedCode = selected.code;

  const run = async () => {
    if (!file) return;
    if (!window.confirm(
      `orderlist의 운송장번호를 사방넷에 바로 등록합니다.\n택배사: ${selected.label} (코드 ${resolvedCode || '미설정'})\n\n전송할까요?`
    )) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await processSabangFruitTracking(file, resolvedCode || undefined);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : '사방넷 송장 전송 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-purple-200 p-6 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-purple-50 rounded-xl flex items-center justify-center text-xl">📮</div>
          <div>
            <h3 className="text-base font-bold text-gray-900">사방넷 송장 자동전송 (orderlist)</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {supplierLabel} 거래처 회신(orderlist)을 올리면 운송장번호를 사방넷에 자동 등록합니다.
              <b> 사방넷 수집으로 만든 발주서의 회신에만 사용하세요</b> (D열 주문번호가 사방넷 번호여야 매칭됩니다).
            </p>
          </div>
        </div>
        {onHide && (
          <button onClick={onHide} title="이 카드를 숨깁니다 (언제든 보이기로 복원)"
            className="shrink-0 px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-semibold text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition">
            숨기기
          </button>
        )}
      </div>

      <FileUpload
        label={`${supplierLabel} 거래처 회신(orderlist) 파일`}
        file={file}
        onFileSelect={(f) => { setFile(f || null); setResult(null); setError(''); }}
      />

      <div>
        <span className="mb-1.5 block text-xs font-medium text-gray-500">
          발송 택배사 (발주처마다 다름 — 이 회신 건의 실제 택배사를 선택)
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          {COURIERS.map((c) => (
            <button key={c.id} type="button"
              onClick={() => { setCourier(c.id); setResult(null); }}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${
                courier === c.id
                  ? 'border-purple-500 bg-purple-500 text-white shadow-sm'
                  : 'border-purple-300 text-purple-700 hover:bg-purple-100'
              }`}>
              {c.label}{c.id !== 'custom' && c.code ? ` (${c.code})` : ''}
            </button>
          ))}
          {courier === 'custom' && (
            <input value={customCode} onChange={(e) => setCustomCode(e.target.value)} placeholder="사방넷 택배사코드"
              className="w-36 rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none focus:border-purple-400 focus:ring-2 focus:ring-purple-200" />
          )}
          <button type="button" onClick={detectCodes} disabled={detecting}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-100 disabled:opacity-50 transition">
            {detecting ? '인식 중...' : '🔍 코드 자동 인식'}
          </button>
        </div>
        {courier !== 'custom' && !resolvedCode && (
          <p className="mt-1.5 text-xs text-amber-700">
            ⚠️ {selected.label}의 사방넷 코드가 미설정입니다. 코드를 모르면 <b>코드 자동 인식</b> 버튼을 누르세요
            (최근 출고완료 주문의 실제 코드·송장 패턴에서 알아냅니다).
          </p>
        )}
        {detectMsg && <p className="mt-1.5 text-xs font-medium text-gray-600">{detectMsg}</p>}
        {detected && detected.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {detected.map((c) => (
              <button key={c.code} type="button"
                onClick={() => { setCourier('custom'); setCustomCode(c.code); setResult(null); }}
                className="rounded-lg border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 transition">
                코드 {c.code} · {c.count}건{c.guess ? ` · ${c.guess}` : ''}{c.sample ? ` · 예 ${c.sample}` : ''}
              </button>
            ))}
          </div>
        )}
      </div>

      <div>
        <button onClick={run} disabled={!file || loading}
          className="bg-purple-600 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-purple-700
                     disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2">
          {loading ? '전송 중...' : '✅ 확인 — 사방넷 송장 전송'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-xl p-4">
          <p className="text-sm font-bold text-green-800 mb-1">사방넷 송장 전송 완료</p>
          <p className="text-sm text-green-700">전송 {result.sent ?? result.total}건 (택배사코드 {result.tak_code})</p>
          {result.result && (result.result as Record<string, unknown>).raw != null && (
            <p className="mt-1 text-xs text-gray-500 break-all">응답: {String((result.result as Record<string, unknown>).raw).slice(0, 300)}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────
function UnifiedProcessPage() {
  const { productId } = useParams<{ productId: string }>();
  const navigate = useNavigate();
  const { user } = useUser();
  const userId = user?.user_id ?? 'anon';
  const [prefs, setPrefs] = useState(() => loadToolPrefs(userId));
  useEffect(() => {
    setPrefs(loadToolPrefs(userId));
  }, [userId]);

  const config = productId ? productConfigs[productId] : undefined;

  const titleOf = (slot: string, fallback: string) =>
    prefs.sectionTitles[`unified:${productId}:${slot}`] ?? fallback;
  const saveTitle = (slot: string, next: string) =>
    setPrefs(setSectionTitle(userId, `unified:${productId}:${slot}`, next));

  if (!config) {
    return (
      <div className="text-center py-20">
        <p className="text-6xl mb-4">🔍</p>
        <h2 className="text-xl font-bold text-gray-900 mb-2">페이지를 찾을 수 없습니다</h2>
        <button onClick={() => navigate('/orders')} className="text-indigo-600 font-semibold hover:text-indigo-700">
          도구 목록으로 돌아가기
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* 뒤로가기 */}
      <button
        onClick={() => navigate('/orders')}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700
                   font-medium mb-6 group"
      >
        <svg className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        도구 목록으로 돌아가기
      </button>

      {/* 헤더 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 mb-6 animate-slide-up">
        <div className="flex items-center gap-4">
          <div className={`w-14 h-14 ${config.bgClass} rounded-2xl flex items-center justify-center text-3xl`}>
            {config.icon}
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900">
              <EditableTitle value={titleOf('header', config.title)} onSave={(t) => saveTitle('header', t)} />
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">{config.description}</p>
          </div>
        </div>
      </div>

      {/* 사방넷 자동수집 — 과일(Itsoft) 주문을 API로 끌어와 발주서 생성 */}
      {(productId === 'myeongi' || productId === 'kolrabi') && (
        <div className="mb-4 animate-slide-up">
          <SabangHideWrap
            storageKey={`sabang-order-hidden:${productId}`}
            title={`사방넷 주문 자동수집 → ${productId === 'kolrabi' ? '제주다팜' : '쥬얼리프룻'} 발주서`}
          >
            {(onHide) => (
              <SabangOrderCard
                section={productId as 'myeongi' | 'kolrabi'}
                supplierLabel={productId === 'kolrabi' ? '제주다팜' : '쥬얼리프룻'}
                onHide={onHide}
              />
            )}
          </SabangHideWrap>
        </div>
      )}

      {/* 두 섹션 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-slide-up">
        <ProcessSection
          section={config.order}
          title={titleOf('order', config.order.title)}
          onTitleSave={(t) => saveTitle('order', t)}
        />
        <ProcessSection
          section={config.tracking}
          title={titleOf('tracking', config.tracking.title)}
          onTitleSave={(t) => saveTitle('tracking', t)}
        />
      </div>

      {/* 사방넷 송장 자동전송 — 회신(orderlist) 업로드 시 사방넷에 운송장 등록 */}
      {(productId === 'myeongi' || productId === 'kolrabi') && (
        <div className="mt-4 animate-slide-up">
          <SabangHideWrap
            storageKey={`sabang-tracking-hidden:${productId}`}
            title="사방넷 송장 자동전송 (orderlist)"
          >
            {(onHide) => (
              <SabangTrackingCard
                supplierLabel={productId === 'kolrabi' ? '제주다팜' : '쥬얼리'}
                onHide={onHide}
              />
            )}
          </SabangHideWrap>
        </div>
      )}

      {/* 토스 운송장 자동등록 (API) — 명이(쥬얼리) · 콜라비(제주다팜 미니밤호박) 페이지 */}
      {(productId === 'myeongi' || productId === 'kolrabi') && (
        <div className="mt-4 animate-slide-up">
          <TossApiTrackingCard supplierLabel={productId === 'kolrabi' ? '제주다팜' : '쥬얼리'} />
        </div>
      )}

      {/* 당근마켓 주문 발주 (텍스트 붙여넣기) — 명이(쥬얼리) 페이지 */}
      {productId === 'myeongi' && (
        <div className="mt-4 animate-slide-up">
          <DaangnOrderCard />
        </div>
      )}

      {/* 이벤트 당첨자 발주 (선택 섹션) */}
      {config.event && (
        <div className="mt-4 animate-slide-up">
          <ProcessSection
            section={config.event}
            title={titleOf('event', config.event.title)}
            onTitleSave={(t) => saveTitle('event', t)}
          />
        </div>
      )}
    </div>
  );
}

export default UnifiedProcessPage;
