import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import FileUpload from '../components/FileUpload';
import { processFile, downloadBlob, ProcessResult } from '../api';

// ── 타입 ──────────────────────────────────────────────────────────
interface FileConfig { key: string; label: string; }

interface SectionConfig {
  title: string;
  icon: string;
  apiToolId: string;
  files: FileConfig[];
  buttonLabel: string;
}

interface ProductConfig {
  title: string;
  description: string;
  icon: string;
  bgClass: string;
  order: SectionConfig;
  tracking: SectionConfig;
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
    title: '콜라비',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🥬',
    bgClass: 'bg-green-50',
    order: {
      title: '발주서 생성',
      icon: '📋',
      apiToolId: 'kolrabi-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
      buttonLabel: '발주서 생성',
    },
    tracking: {
      title: '콜라비+성주참외 혼합(알뜰)과 운송장번호 입력',
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
    title: '명이나물',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🌿',
    bgClass: 'bg-green-50',
    order: {
      title: '발주서 생성',
      icon: '📋',
      apiToolId: 'myeongi-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
      buttonLabel: '발주서 생성',
    },
    tracking: {
      title: '운송장번호 입력',
      icon: '📦',
      apiToolId: 'myeongi-tracking',
      files: [
        { key: 'orderlist', label: 'Orderlist 파일' },
        { key: 'delivery', label: 'DeliveryList 파일' },
      ],
      buttonLabel: '운송장 입력',
    },
  },
  tomato: {
    title: '대저토마토·성주참외(중소/로얄)·남해땅두릅',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🍅',
    bgClass: 'bg-red-50',
    order: {
      title: '발주서 생성',
      icon: '📋',
      apiToolId: 'tomato-order',
      files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
      buttonLabel: '발주서 생성',
    },
    tracking: {
      title: '대저토마토·성주참외(중소/로얄)·남해땅두릅 운송장번호 입력',
      icon: '📦',
      apiToolId: 'tomato-tracking',
      files: [
        { key: 'tomato_reply', label: '대저토마토·성주참외(중소/로얄) 회신 파일' },
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

// ── 섹션 컴포넌트 ─────────────────────────────────────────────────
function ProcessSection({ section }: { section: SectionConfig }) {
  const [files, setFiles] = useState<Record<string, File | null>>({});
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
      const res = await processFile(section.apiToolId, fileMap, {});
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
        <h3 className="text-base font-bold text-gray-900">{section.title}</h3>
      </div>

      {/* 파일 업로드 */}
      <div className="space-y-4">
        {section.files.map((f) => (
          <FileUpload
            key={f.key}
            label={f.label}
            file={files[f.key] || null}
            onFileSelect={handleFileSelect(f.key)}
          />
        ))}
      </div>

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

// ── 메인 페이지 ───────────────────────────────────────────────────
function UnifiedProcessPage() {
  const { productId } = useParams<{ productId: string }>();
  const navigate = useNavigate();

  const config = productId ? productConfigs[productId] : undefined;

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
            <h2 className="text-xl font-bold text-gray-900">{config.title}</h2>
            <p className="text-sm text-gray-500 mt-0.5">{config.description}</p>
          </div>
        </div>
      </div>

      {/* 두 섹션 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-slide-up">
        <ProcessSection section={config.order} />
        <ProcessSection section={config.tracking} />
      </div>
    </div>
  );
}

export default UnifiedProcessPage;
