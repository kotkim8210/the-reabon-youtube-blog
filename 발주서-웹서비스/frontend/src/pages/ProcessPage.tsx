import { useState, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import FileUpload from '../components/FileUpload';
import { processFile, downloadBlob, ProcessResult } from '../api';

interface FileConfig {
  key: string;
  label: string;
  optional?: boolean;
}

interface SelectOption {
  value: string;
  label: string;
}

interface ExtraCheckbox {
  key: string;
  label: string;
  description?: string;
  defaultValue: boolean;
}

interface ToolConfig {
  title: string;
  description: string;
  icon: string;
  files: FileConfig[];
  color: string;
  colorClasses: {
    bg: string;
    text: string;
    badge: string;
  };
  extraSelect?: {
    key: string;
    label: string;
    options: SelectOption[];
    defaultValue: string;
  };
  extraCheckboxes?: ExtraCheckbox[];
  tossDateRange?: boolean; // 토스 API 날짜 범위 선택 UI 표시 여부
}

const toolConfigs: Record<string, ToolConfig> = {
  'kolrabi-order': {
    title: '콜라비 발주서 생성',
    description:
      'DeliveryList에서 콜라비 주문을 추출하여 제주다팜 발주서를 생성합니다.',
    icon: '🥬',
    files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
    color: 'green',
    colorClasses: {
      bg: 'bg-green-50',
      text: 'text-green-700',
      badge: 'bg-green-100 text-green-700',
    },
  },
  'chamdureup-order': {
    title: '참두릅 발주서 생성',
    description:
      'DeliveryList에서 참두릅 주문을 추출하여 jaehwan0330 발주서를 생성합니다.',
    icon: '🌱',
    files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
    color: 'green',
    colorClasses: {
      bg: 'bg-green-50',
      text: 'text-green-700',
      badge: 'bg-green-100 text-green-700',
    },
  },
  'chamdureup-tracking': {
    title: '참두릅 운송장번호 입력',
    description:
      '참두릅 orderlist의 운송장번호를 DeliveryList에 자동으로 매핑합니다.',
    icon: '🌱📦',
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
    color: 'green',
    colorClasses: {
      bg: 'bg-green-50',
      text: 'text-green-700',
      badge: 'bg-green-100 text-green-700',
    },
  },
  'myeongi-order': {
    title: '명이나물 발주서 생성',
    description:
      'DeliveryList에서 명이나물 주문을 추출하여 pbfcompany 발주서를 생성합니다.',
    icon: '🌿',
    files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
    color: 'green',
    colorClasses: {
      bg: 'bg-green-50',
      text: 'text-green-700',
      badge: 'bg-green-100 text-green-700',
    },
  },
  'tomato-order': {
    title: '대저토마토·성주참외(중소/로얄)·남해땅두릅 발주서 생성',
    description:
      'DeliveryList에서 대저토마토·성주참외 중소/로얄·남해땅두릅 주문을 추출합니다. 성주참외 가정용 혼합과가 함께 있으면 제주다팜 알뜰참외 발주서를 별도 파일로 추가 출력합니다.',
    icon: '🍅🍈🌿',
    files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
    color: 'red',
    colorClasses: {
      bg: 'bg-red-50',
      text: 'text-red-700',
      badge: 'bg-red-100 text-red-700',
    },
  },
  'goguma-order': {
    title: '고구마 발주서 생성',
    description:
      'DeliveryList에서 고구마 주문을 추출하여 해달 발주서를 생성합니다. 올웨이즈·토스 주문도 함께 처리 가능합니다.',
    icon: '🍠',
    files: [
      { key: 'delivery', label: 'DeliveryList 파일' },
      { key: 'alwayz', label: '올웨이즈 주문내역 (선택)', optional: true },
      { key: 'toss', label: '토스 주문내역 (선택)', optional: true },
    ],
    color: 'orange',
    colorClasses: {
      bg: 'bg-orange-50',
      text: 'text-orange-700',
      badge: 'bg-orange-100 text-orange-700',
    },
    tossDateRange: true,
  },
  'myeongi-tracking': {
    title: '명이나물 운송장번호 입력',
    description:
      '명이나물 orderlist의 운송장번호를 DeliveryList에 자동으로 매핑합니다.',
    icon: '🌿📦',
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
    color: 'green',
    colorClasses: {
      bg: 'bg-green-50',
      text: 'text-green-700',
      badge: 'bg-green-100 text-green-700',
    },
  },
  'tomato-tracking': {
    title: '대저토마토·성주참외(중소/로얄)·남해땅두릅 운송장번호 입력',
    description:
      '회신 파일의 운송장번호와 택배사(K열)를 DeliveryList에 자동으로 매핑합니다. 성주참외 가정용 혼합과는 콜라비+성주참외 혼합(알뜰)과 메뉴를 사용하세요.',
    icon: '🍅🍈🌿📦',
    files: [
      { key: 'tomato_reply', label: '대저토마토·성주참외(중소/로얄) 회신 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
    color: 'red',
    colorClasses: {
      bg: 'bg-red-50',
      text: 'text-red-700',
      badge: 'bg-red-100 text-red-700',
    },
  },
  'tracking-input': {
    title: '콜라비+성주참외 혼합(알뜰)과 운송장번호 입력',
    description:
      '콜라비와 성주참외 가정용 혼합과가 함께 들어 있는 Orderlist 파일의 운송장번호를 DeliveryList에 자동으로 매핑합니다.',
    icon: '📦',
    files: [
      { key: 'orderlist', label: 'Orderlist 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
    color: 'blue',
    colorClasses: {
      bg: 'bg-blue-50',
      text: 'text-blue-700',
      badge: 'bg-blue-100 text-blue-700',
    },
  },
  'goguma-tracking': {
    title: '고구마 운송장번호 입력',
    description:
      '해달 발주서의 운송장번호를 DeliveryList에 자동으로 매핑합니다.',
    icon: '🍠📦',
    files: [
      { key: 'haedal', label: '해달 발주서 파일' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
    color: 'amber',
    colorClasses: {
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      badge: 'bg-amber-100 text-amber-700',
    },
  },
  'gaegeolmu-order': {
    title: '게걸무씨앗기름 발주서 생성',
    description:
      'DeliveryList에서 게걸무씨앗기름 주문을 추출하여 발주서를 생성합니다.',
    icon: '🌾',
    files: [{ key: 'delivery', label: 'DeliveryList 파일' }],
    color: 'amber',
    colorClasses: {
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      badge: 'bg-amber-100 text-amber-700',
    },
  },
  'gaegeolmu-tracking': {
    title: '게걸무씨앗기름 운송장번호 입력',
    description:
      '게걸무 택배발송 파일(B열=운송장, C열=이름)의 운송장번호를 DeliveryList(AA열=이름, E열=운송장)에 자동 매핑합니다. 동명이인 자동 감지.',
    icon: '🌾📦',
    files: [
      { key: 'tracking', label: '게걸무 택배발송 파일 (B=운송장, C=이름)' },
      { key: 'delivery', label: 'DeliveryList 파일' },
    ],
    color: 'amber',
    colorClasses: {
      bg: 'bg-amber-50',
      text: 'text-amber-700',
      badge: 'bg-amber-100 text-amber-700',
    },
  },
};

function ProcessPage() {
  const { toolId } = useParams<{ toolId: string }>();
  const navigate = useNavigate();

  const config = toolId ? toolConfigs[toolId] : undefined;

  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [extraValues, setExtraValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    if (config?.extraSelect) {
      init[config.extraSelect.key] = config.extraSelect.defaultValue;
    }
    if (config?.extraCheckboxes) {
      for (const cb of config.extraCheckboxes) {
        init[cb.key] = cb.defaultValue ? 'true' : 'false';
      }
    }
    // 토스 날짜 범위 기본값: 오늘
    if (config?.tossDateRange) {
      const today = new Date().toISOString().slice(0, 10);
      init['toss_from_date'] = today;
      init['toss_to_date'] = today;
    }
    return init;
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [error, setError] = useState('');

  const allFilesUploaded = useMemo(() => {
    if (!config) return false;
    return config.files.filter((f) => !f.optional).every((f) => files[f.key] != null);
  }, [config, files]);

  if (!config || !toolId) {
    return (
      <div className="text-center py-20">
        <p className="text-6xl mb-4">🔍</p>
        <h2 className="text-xl font-bold text-gray-900 mb-2">
          도구를 찾을 수 없습니다
        </h2>
        <p className="text-gray-500 mb-6">
          요청하신 도구가 존재하지 않습니다.
        </p>
        <button
          onClick={() => navigate('/orders')}
          className="text-indigo-600 font-semibold hover:text-indigo-700"
        >
          도구 목록으로 돌아가기
        </button>
      </div>
    );
  }

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
      for (const [key, file] of Object.entries(files)) {
        if (file) fileMap[key] = file;
      }

      const res = await processFile(toolId, fileMap, extraValues);
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
    setFiles({});
    setResult(null);
    setError('');
  };

  const formatStats = (stats: Record<string, unknown>): string[] => {
    const lines: string[] = [];
    for (const [key, value] of Object.entries(stats)) {
      if (typeof value === 'number') {
        lines.push(`${key}: ${value}건`);
      } else {
        lines.push(`${key}: ${value}`);
      }
    }
    return lines;
  };

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
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        도구 목록으로 돌아가기
      </button>

      {/* Tool Header */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 mb-6 animate-slide-up">
        <div className="flex items-center gap-4">
          <div
            className={`w-14 h-14 ${config.colorClasses.bg} rounded-2xl flex items-center justify-center text-3xl`}
          >
            {config.icon}
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900">{config.title}</h2>
            <p className="text-sm text-gray-500 mt-0.5">{config.description}</p>
          </div>
        </div>
      </div>

      {/* File Uploads */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 mb-6 animate-slide-up">
        <h3 className="text-base font-bold text-gray-900 mb-4">파일 업로드</h3>

        {/* Extra Select (e.g. delivery company) */}
        {config.extraSelect && (
          <div className="mb-5">
            <label className="block text-sm font-semibold text-gray-700 mb-2">
              {config.extraSelect.label}
            </label>
            <select
              value={extraValues[config.extraSelect.key] || config.extraSelect.defaultValue}
              onChange={(e) =>
                setExtraValues((prev) => ({
                  ...prev,
                  [config.extraSelect!.key]: e.target.value,
                }))
              }
              className="w-full max-w-xs px-4 py-2.5 rounded-xl border border-gray-300 text-sm
                         font-medium bg-white
                         focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 outline-none
                         transition-all"
            >
              {config.extraSelect.options.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="space-y-5">
          {config.files.map((fileConfig) => (
            <FileUpload
              key={fileConfig.key}
              label={fileConfig.label}
              file={files[fileConfig.key] || null}
              onFileSelect={handleFileSelect(fileConfig.key)}
            />
          ))}
        </div>

        {/* Toss API Date Range Picker */}
        {config.tossDateRange && (
          <div className="mt-5 p-4 rounded-xl border border-orange-200 bg-orange-50/50">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-bold text-gray-800">🛒 토스 API 주문 수집</span>
              <div className="flex gap-1.5">
                {[
                  { label: '오늘', days: 0 },
                  { label: '2일', days: 1 },
                  { label: '3일', days: 2 },
                  { label: '주말(금~일)', days: 3 },
                  { label: '수집안함', days: -1 },
                ].map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => {
                      if (preset.days === -1) {
                        setExtraValues((prev) => ({
                          ...prev,
                          toss_from_date: '',
                          toss_to_date: '',
                        }));
                      } else {
                        const to = new Date();
                        const from = new Date();
                        from.setDate(from.getDate() - preset.days);
                        setExtraValues((prev) => ({
                          ...prev,
                          toss_from_date: from.toISOString().slice(0, 10),
                          toss_to_date: to.toISOString().slice(0, 10),
                        }));
                      }
                    }}
                    className="px-2 py-1 text-xs font-medium rounded-lg border border-orange-300
                               hover:bg-orange-100 text-orange-700 transition-colors"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <label className="block text-xs text-gray-500 mb-1">시작일</label>
                <input
                  type="date"
                  value={extraValues['toss_from_date'] || ''}
                  onChange={(e) =>
                    setExtraValues((prev) => ({ ...prev, toss_from_date: e.target.value }))
                  }
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm
                             focus:ring-2 focus:ring-orange-300 focus:border-orange-400 outline-none"
                />
              </div>
              <span className="text-gray-400 mt-5">~</span>
              <div className="flex-1">
                <label className="block text-xs text-gray-500 mb-1">종료일</label>
                <input
                  type="date"
                  value={extraValues['toss_to_date'] || ''}
                  onChange={(e) =>
                    setExtraValues((prev) => ({ ...prev, toss_to_date: e.target.value }))
                  }
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm
                             focus:ring-2 focus:ring-orange-300 focus:border-orange-400 outline-none"
                />
              </div>
            </div>
            {!extraValues['toss_from_date'] && (
              <p className="text-xs text-gray-400 mt-2">※ 날짜 미선택 시 토스 API 수집을 건너뜁니다.</p>
            )}
          </div>
        )}

        {/* Extra Checkboxes (e.g. include toss orders) */}
        {config.extraCheckboxes && config.extraCheckboxes.length > 0 && (
          <div className="mt-5 space-y-3">
            {config.extraCheckboxes.map((cb) => (
              <label
                key={cb.key}
                className="flex items-start gap-3 p-3 rounded-xl border border-gray-200
                           hover:bg-gray-50 cursor-pointer transition-colors"
              >
                <input
                  type="checkbox"
                  checked={extraValues[cb.key] === 'true'}
                  onChange={(e) =>
                    setExtraValues((prev) => ({
                      ...prev,
                      [cb.key]: e.target.checked ? 'true' : 'false',
                    }))
                  }
                  className="mt-0.5 w-4 h-4 text-indigo-600 rounded border-gray-300
                             focus:ring-indigo-500"
                />
                <div>
                  <span className="text-sm font-semibold text-gray-800">{cb.label}</span>
                  {cb.description && (
                    <p className="text-xs text-gray-500 mt-0.5">{cb.description}</p>
                  )}
                </div>
              </label>
            ))}
          </div>
        )}

        {/* Action Buttons */}
        <div className="mt-6 flex items-center gap-3">
          <button
            onClick={handleProcess}
            disabled={!allFilesUploaded || loading}
            className="bg-indigo-600 text-white px-6 py-3 rounded-xl font-semibold text-sm
                       hover:bg-indigo-700 active:bg-indigo-800
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all duration-200
                       flex items-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                처리 중...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                처리하기
              </>
            )}
          </button>
          {(Object.keys(files).length > 0 || result || error) && (
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

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-5 mb-6 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-red-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.07 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <div>
              <h4 className="text-sm font-bold text-red-800 mb-0.5">오류 발생</h4>
              <p className="text-sm text-red-600">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Success Result */}
      {result && (
        <div className="bg-green-50 border border-green-200 rounded-2xl p-5 mb-6 animate-fade-in">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-green-100 rounded-xl flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div className="flex-1">
              <h4 className="text-sm font-bold text-green-800 mb-1">처리 완료</h4>
              {result.stats && (
                <div className="space-y-0.5 mb-3">
                  {formatStats(result.stats).map((line, i) => (
                    <p key={i} className="text-sm text-green-700">
                      {line}
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
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {result.filename} 다운로드
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading Overlay */}
      {loading && (
        <div className="bg-white border border-gray-200 rounded-2xl p-8 text-center animate-fade-in">
          <svg
            className="animate-spin w-10 h-10 text-indigo-600 mx-auto mb-4"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          <p className="text-sm font-semibold text-gray-900">파일을 처리하고 있습니다...</p>
          <p className="text-xs text-gray-500 mt-1">잠시만 기다려주세요</p>
        </div>
      )}
    </div>
  );
}

export default ProcessPage;
