import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Pencil, Check, X } from 'lucide-react';
import FileUpload from '../components/FileUpload';
import { processFile, downloadBlob, ProcessResult, processTossWatermelonTracking } from '../api';
import { useUser } from '../App';
import { loadToolPrefs, setSectionTitle } from '../lib/toolCatalog';

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
    title: '콜라비·초당옥수수·미니밤호박 1kg(제주다팜)',
    description: '취급품목: 콜라비·초당옥수수·미니밤호박(보우짱 로얄과) 1kg 제주다팜 발주서 생성 + 운송장번호 입력 · 미니밤호박 3·5·10kg과 애플초당옥수수·성주참외는 명이나물(쥬얼리) 메뉴',
    icon: '🥬',
    bgClass: 'bg-green-50',
    order: {
      title: '콜라비·초당옥수수·미니밤호박 1kg 발주서 생성',
      icon: '📋',
      apiToolId: 'kolrabi-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
      buttonLabel: '발주서 생성',
    },
    tracking: {
      title: '콜라비·초당옥수수·미니밤호박 1kg 운송장번호 입력',
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
    title: '명이나물+애플초당옥수수+망고수박+수박+성주참외+신비복숭아+홍감자+미니밤호박',
    description: '쥬얼리프룻 발주서 생성 + 운송장번호 입력 · 취급품목: 명이나물·애플초당옥수수·망고수박·수박·성주참외·신비복숭아·홍감자·미니밤호박(보우짱 로얄과 3·5·10kg, 1kg은 제주다팜 메뉴)',
    icon: '🌿',
    bgClass: 'bg-green-50',
    order: {
      title: '명이나물+애플초당옥수수+망고수박+수박+성주참외+신비복숭아+홍감자+미니밤호박 발주서 생성',
      icon: '📋',
      apiToolId: 'myeongi-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일 (쿠팡)' }],
      buttonLabel: '발주서 생성',
      tossDateRange: true,
      tossDefaultDays: 1,  // 기본 2일(어제~오늘). '오늘' 버튼은 추가발주용으로 유지
      tossDateTitle: '토스 주문 수집 (쥬얼리)',
      tossDateHint: '기본 2일(어제~오늘) 토스 주문(수박·성주참외·신비복숭아 1·2kg·망고수박·홍감자)을 쥬얼리프룻 발주서에 합칩니다. 신비복숭아 3·4kg은 제이비티 메뉴로. 배송중·송장입력 건은 자동 제외. (추가발주는 "오늘", 안 합치려면 "수집안함")',
    },
    tracking: {
      title: '명이나물+애플초당옥수수+망고수박+수박+성주참외+신비복숭아+홍감자+미니밤호박 운송장번호 입력',
      icon: '📦',
      apiToolId: 'myeongi-tracking',
      files: [
        { key: 'orderlist', label: 'Orderlist 파일' },
        { key: 'delivery', label: 'DeliveryList 파일' },
      ],
      buttonLabel: '운송장 입력',
    },
    event: {
      title: '라이브 이벤트 당첨자 발주서 생성 (참외·신비복숭아)',
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
  return Object.entries(stats).map(([key, value]) =>
    typeof value === 'number' ? `${key}: ${value}건` : `${key}: ${value}`
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
    if (!section.tossDateRange) return {} as Record<string, string>;
    return { toss_from_date: localDateString(-(section.tossDefaultDays ?? 0)), toss_to_date: localDateString() };
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
              ].map((preset) => (
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
                  className="rounded-lg border border-orange-300 px-2 py-1 text-xs font-semibold text-orange-700 transition hover:bg-orange-100"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
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
function TossApiTrackingCard() {
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
            쥬얼리 거래처 회신(orderlist) 파일을 올리면 토스 주문에 운송장번호를 토스 API로 자동 등록합니다.
            결제완료 주문은 상품준비중으로 자동 전환됩니다.
          </p>
          <p className="text-xs font-semibold text-amber-700 mt-1">
            ⚠️ DeliveryList(쿠팡 송장입력본)가 아니라, 토스 고객 송장이 들어있는 <b>거래처 회신(orderlist)</b> 파일을 올려야 합니다.
          </p>
        </div>
      </div>

      <FileUpload
        label="쥬얼리 거래처 회신(orderlist) 파일"
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
              성공 0건이면 올린 파일이 DeliveryList(쿠팡)일 수 있어요. 토스 고객이 포함된 <b>쥬얼리 회신(orderlist)</b> 파일인지 확인하세요.
            </p>
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

      {/* 토스 운송장 자동등록 (API) — 명이(쥬얼리) 페이지 전용 */}
      {productId === 'myeongi' && (
        <div className="mt-4 animate-slide-up">
          <TossApiTrackingCard />
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
