import { Fragment, type DragEvent, useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Boxes,
  ChevronDown,
  ChevronRight,
  Database,
  Download,
  FileSpreadsheet,
  Layers3,
  PackageSearch,
  RefreshCw,
  Rocket,
  Upload,
  type LucideIcon,
} from 'lucide-react';

import {
  downloadBlob,
  downloadSupplierPriceMonitorWorkbook,
  fetchSupplierPriceMonitor,
  getOrderAutomationOverview,
  processDanharuOrder,
  processDanharuTracking,
  type OrderAutomationOverview,
  type SupplierPriceMonitorData,
} from '../api';
import { useUser } from '../App';

const SUPPLIER_MONITOR_KEYS = [
  { key: 'kolrabi', accent: 'sky' },
  { key: 'corn-jbt', accent: 'amber' },
  { key: 'chamoe-jewelry', accent: 'emerald' },
  { key: 'tomato-jbt', accent: 'sky' },
  { key: 'watermelon-jewelry', accent: 'emerald' },
  { key: 'dureup-jbt', accent: 'amber' },
  { key: 'bamhobak-jewelry', accent: 'emerald' },
  { key: 'potato-jeju', accent: 'sky' },
  { key: 'baekdo-jewelry', accent: 'emerald' },
] as const;

// 한시 모니터: 해당 날짜(YYYY-MM-DD)가 지나면 화면에서 자동 숨김
// (신비복숭아 peach-jewelry·peach-jbt는 2026-07 품절로 제거)
const SUPPLIER_MONITOR_EXPIRY: Partial<Record<string, string>> = {};

type SupplierMonitorKey = (typeof SUPPLIER_MONITOR_KEYS)[number]['key'];
type AccentTone = (typeof SUPPLIER_MONITOR_KEYS)[number]['accent'];

const HIDDEN_SUPPLIER_MONITORS_STORAGE_KEY = 'danharu.marginDefense.hiddenMonitors';
const DEFAULT_HIDDEN_SUPPLIER_MONITOR_KEYS: SupplierMonitorKey[] = ['tomato-jbt'];
const SUPPLIER_MONITOR_LABELS: Record<SupplierMonitorKey, string> = {
  kolrabi: '콜라비',
  'corn-jbt': '초당옥수수',
  'chamoe-jewelry': '성주참외(쥬얼리)',
  'tomato-jbt': '대저토마토',
  'watermelon-jewelry': '망고수박',
  'dureup-jbt': '남해땅두릅',
  // 발주처가 옵션별로 갈리는 상품은 한 파일에 모아서 받는다(1kg 제주다팜 + 3·5·10kg 쥬얼리 등)
  'bamhobak-jewelry': '미니밤호박 1·3·5·10kg(제주다팜+쥬얼리)',
  'potato-jeju': '홍감자(제주다팜)',
  'baekdo-jewelry': '백도 딱딱이복숭아 2·4kg(제주다팜)',
};

/** 한시 모니터 만료 필터: 오늘이 expiresOn(YYYY-MM-DD)을 지나면 제외 */
function activeSupplierMonitorKeys(): typeof SUPPLIER_MONITOR_KEYS[number][] {
  const today = new Date();
  const todayIso = new Date(today.getTime() - today.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  return SUPPLIER_MONITOR_KEYS.filter((m) => {
    const exp = SUPPLIER_MONITOR_EXPIRY[m.key];
    return !exp || todayIso <= exp;
  });
}

function isSupplierMonitorKey(value: string): value is SupplierMonitorKey {
  return SUPPLIER_MONITOR_KEYS.some((monitor) => monitor.key === value);
}

function readHiddenSupplierMonitorKeys(): SupplierMonitorKey[] {
  try {
    const stored = window.localStorage.getItem(HIDDEN_SUPPLIER_MONITORS_STORAGE_KEY);
    if (!stored) return DEFAULT_HIDDEN_SUPPLIER_MONITOR_KEYS;
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return DEFAULT_HIDDEN_SUPPLIER_MONITOR_KEYS;
    return parsed.filter((value): value is SupplierMonitorKey => typeof value === 'string' && isSupplierMonitorKey(value));
  } catch {
    return DEFAULT_HIDDEN_SUPPLIER_MONITOR_KEYS;
  }
}

type SupplierMonitorEntry = {
  key: SupplierMonitorKey;
  accent: AccentTone;
  data: SupplierPriceMonitorData;
};

type CombinedMonitorRow = {
  monitorKey: SupplierMonitorKey;
  accent: AccentTone;
  title: string;
  supplierName: string;
  productName: string;
  checkedAt: string;
  optionName: string;
  supplierOptionName?: string;
  cell: string;
  previousPrice: number;
  currentPrice: number;
  diff: number;
  signal: 'blue' | 'red' | 'same';
  signalLabel: string;
  margin?: number | null;
  marginNegative?: boolean;
};

type MonitorGroup = {
  key: SupplierMonitorKey;
  accent: AccentTone;
  title: string;
  supplierName: string;
  productName: string;
  checkedAt: string;
  rows: CombinedMonitorRow[];
  representative: CombinedMonitorRow;
  upCount: number;
  downCount: number;
  sameCount: number;
  negativeMarginCount: number;
};

function dateString(offsetDays = 0): string {
  const current = new Date();
  current.setDate(current.getDate() + offsetDays);
  const localTime = current.getTime() - current.getTimezoneOffset() * 60 * 1000;
  return new Date(localTime).toISOString().slice(0, 10);
}

function formatDayLabel(value: string): string {
  return value.slice(5).replace('-', '.');
}

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString('ko-KR', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatCurrency(value: number): string {
  return `₩${value.toLocaleString('ko-KR')}`;
}

function summarizeOrderStats(stats?: Record<string, unknown> | null): string {
  if (!stats) return '';
  const rows = typeof stats.total_rows === 'number' ? stats.total_rows : 0;
  const quantity = typeof stats.total_quantity === 'number' ? stats.total_quantity : 0;
  return `${rows.toLocaleString('ko-KR')}건 / ${quantity.toLocaleString('ko-KR')}개`;
}

function summarizeTrackingStats(stats?: Record<string, unknown> | null): string {
  if (!stats) return '';
  const filled = typeof stats.filled === 'number' ? stats.filled : 0;
  const skipped = typeof stats.skipped === 'number' ? stats.skipped : 0;
  const replyFiles = typeof stats.reply_files === 'number' ? stats.reply_files : 0;
  const processedFiles = typeof stats.processed_files === 'number' ? stats.processed_files : 0;
  const base = `${filled.toLocaleString('ko-KR')}건 입력 / ${skipped.toLocaleString('ko-KR')}건 스킵`;
  if (replyFiles > 1) {
    return `${base} (${processedFiles.toLocaleString('ko-KR')}개 파일 처리 / 업로드 ${replyFiles.toLocaleString('ko-KR')}개)`;
  }
  return base;
}

function syncStatusLabel(status: string): string {
  if (status === 'synced') return '동기화 완료';
  if (status === 'error') return '동기화 오류';
  if (status === 'pending') return '동기화 대기';
  if (status === 'local_only') return '로컬 저장';
  return status;
}

function accentClass(accent: AccentTone): string {
  if (accent === 'emerald') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (accent === 'sky') return 'border-sky-200 bg-sky-50 text-sky-700';
  return 'border-amber-200 bg-amber-50 text-amber-700';
}

function signalClass(signal: CombinedMonitorRow['signal']): string {
  if (signal === 'blue') return 'bg-blue-50 text-blue-700';
  if (signal === 'red') return 'bg-rose-50 text-rose-700';
  return 'bg-slate-100 text-slate-600';
}

function signalLabel(signal: CombinedMonitorRow['signal']): string {
  if (signal === 'blue') return '상승';
  if (signal === 'red') return '하락';
  return '동일';
}

function diffPrefix(signal: CombinedMonitorRow['signal']): string {
  if (signal === 'blue') return '+';
  if (signal === 'red') return '-';
  return '';
}

function optionWeightKg(row: Pick<CombinedMonitorRow, 'optionName' | 'supplierOptionName'>): number {
  const text = `${row.optionName} ${row.supplierOptionName ?? ''}`;
  const kgMatch = text.match(/(\d+(?:\.\d+)?)\s*kg/i);
  if (kgMatch) {
    return Number(kgMatch[1]);
  }

  const gramMatch = text.match(/(\d+(?:\.\d+)?)\s*g/i);
  if (gramMatch) {
    return Number(gramMatch[1]) / 1000;
  }

  return Number.MAX_SAFE_INTEGER;
}

function sortByOptionWeight(
  left: Pick<CombinedMonitorRow, 'optionName' | 'supplierOptionName'>,
  right: Pick<CombinedMonitorRow, 'optionName' | 'supplierOptionName'>,
): number {
  const weightDiff = optionWeightKg(left) - optionWeightKg(right);
  if (weightDiff !== 0) return weightDiff;
  return left.optionName.localeCompare(right.optionName, 'ko-KR');
}

function groupStatusLabel(group: MonitorGroup): string {
  if (group.negativeMarginCount > 0) {
    return `마진 경고 ${group.negativeMarginCount} / 상승 ${group.upCount} / 하락 ${group.downCount}`;
  }
  return `상승 ${group.upCount} / 하락 ${group.downCount} / 동일 ${group.sameCount}`;
}

function UploadField({
  title,
  description,
  tone,
  file,
  onChange,
}: {
  title: string;
  description: string;
  tone: 'amber' | 'sky' | 'emerald';
  file: File | null;
  onChange: (file: File | null) => void;
}) {
  const toneClass =
    tone === 'amber'
      ? 'bg-amber-400/15 text-amber-300'
      : tone === 'sky'
        ? 'bg-sky-400/15 text-sky-300'
        : 'bg-emerald-400/15 text-emerald-300';

  return (
    <label className="block rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-center gap-3">
        <div className={`rounded-xl p-2 ${toneClass}`}>
          <Upload size={18} />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-white">{title}</p>
          <p className="text-xs text-slate-300">{description}</p>
        </div>
      </div>
      <input
        type="file"
        accept=".xlsx,.xls"
        className="mt-4 block w-full text-sm text-slate-200 file:mr-3 file:rounded-full file:border-0 file:bg-white file:px-4 file:py-2 file:text-sm file:font-semibold file:text-slate-900"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      {file && <p className="mt-2 text-xs text-slate-200">{file.name}</p>}
    </label>
  );
}

function MultiUploadField({
  title,
  description,
  tone,
  files,
  onChange,
}: {
  title: string;
  description: string;
  tone: 'amber' | 'sky' | 'emerald';
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const toneClass =
    tone === 'amber'
      ? 'bg-amber-400/15 text-amber-300'
      : tone === 'sky'
        ? 'bg-sky-400/15 text-sky-300'
        : 'bg-emerald-400/15 text-emerald-300';

  const fileKey = (file: File) => `${file.name}__${file.size}__${file.lastModified}`;

  function handleSelect(newFiles: FileList | null) {
    if (!newFiles || newFiles.length === 0) return;
    const incoming = Array.from(newFiles);
    const seen = new Set(files.map(fileKey));
    const merged = [...files];
    for (const f of incoming) {
      const k = fileKey(f);
      if (!seen.has(k)) {
        seen.add(k);
        merged.push(f);
      }
    }
    onChange(merged);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    handleSelect(event.dataTransfer.files);
  }

  function removeAt(idx: number) {
    onChange(files.filter((_, i) => i !== idx));
  }

  return (
    <div
      className="rounded-2xl border border-dashed border-white/15 bg-white/5 p-4 transition hover:border-sky-300/50 hover:bg-white/[0.07]"
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
    >
      <div className="flex items-start gap-3">
        <div className={`rounded-xl p-2 ${toneClass}`}>
          <Upload size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-white">{title}</p>
          <p className="text-xs leading-5 text-slate-300">{description}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-white px-4 py-2 text-sm font-semibold text-slate-900 transition hover:bg-sky-50">
              <Upload size={14} />
              파일 추가
              <input
                type="file"
                accept=".xlsx,.xls"
                multiple
                className="hidden"
                onChange={(event) => {
                  handleSelect(event.target.files);
                  event.target.value = '';
                }}
              />
            </label>
            <span className="text-xs font-medium text-slate-300">
              {files.length > 0 ? `${files.length}개 추가됨` : '여러 파일을 한 번에 선택하거나 끌어다 놓으세요'}
            </span>
          </div>
        </div>
        {files.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="shrink-0 rounded-full bg-white/10 px-3 py-1 text-xs font-semibold text-slate-200 hover:bg-rose-500/20 hover:text-rose-100"
          >
            전체 삭제
          </button>
        )}
      </div>
      {files.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {files.map((f, idx) => (
            <li key={`${fileKey(f)}-${idx}`} className="flex items-center justify-between gap-3 rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-200">
              <span className="min-w-0 truncate">{f.name}</span>
              <button
                type="button"
                onClick={() => removeAt(idx)}
                className="shrink-0 rounded-full bg-white/10 px-2 py-0.5 text-[10px] text-slate-300 hover:bg-rose-500/20 hover:text-rose-200"
              >
                삭제
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint: string;
  icon: LucideIcon;
}) {
  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
        <Icon size={18} className="text-slate-400" />
      </div>
      <p className="mt-4 text-3xl font-black tracking-tight text-slate-900">{value}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500">{hint}</p>
    </article>
  );
}

function SupplierMonitorCard({
  monitor,
  downloading,
  onDownload,
}: {
  monitor: SupplierMonitorEntry;
  downloading: boolean;
  onDownload: (key: SupplierMonitorKey) => void;
}) {
  const representativeOption = [...monitor.data.rows]
    .sort((left, right) =>
      sortByOptionWeight(
        {
          optionName: left.option_name,
          supplierOptionName: left.supplier_option_name,
        },
        {
          optionName: right.option_name,
          supplierOptionName: right.supplier_option_name,
        },
      ),
    )[0]?.option_name ?? monitor.data.product_name;

  return (
    <article className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-bold ${accentClass(monitor.accent)}`}>
              {representativeOption}
            </span>
            <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-bold text-slate-600">
              {monitor.data.total_items}개 옵션
            </span>
          </div>
          <h3 className="mt-3 text-lg font-black text-slate-900">{monitor.data.title}</h3>
          <p className="mt-1 text-sm text-slate-500">{formatDateTime(monitor.data.checked_at)} 기준 비교</p>
        </div>
        <button
          onClick={() => onDownload(monitor.key)}
          disabled={downloading}
          className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {downloading ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
          엑셀 저장
        </button>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-4">
        <div className="rounded-2xl bg-slate-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">상승</p>
          <p className="mt-2 text-2xl font-black text-blue-700">{monitor.data.blue_count}</p>
        </div>
        <div className="rounded-2xl bg-slate-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">하락</p>
          <p className="mt-2 text-2xl font-black text-rose-700">{monitor.data.red_count}</p>
        </div>
        <div className="rounded-2xl bg-slate-50 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">동일</p>
          <p className="mt-2 text-2xl font-black text-slate-700">{monitor.data.same_count}</p>
        </div>
        <div className={`rounded-2xl p-4 ${monitor.data.negative_margin_count ? 'bg-red-50' : 'bg-slate-50'}`}>
          <p className={`text-xs font-semibold uppercase tracking-[0.16em] ${monitor.data.negative_margin_count ? 'text-red-600' : 'text-slate-500'}`}>
            마진 경고
          </p>
          <p className={`mt-2 text-2xl font-black ${monitor.data.negative_margin_count ? 'text-red-700' : 'text-slate-700'}`}>
            {monitor.data.negative_margin_count ?? 0}
          </p>
        </div>
      </div>
    </article>
  );
}

export default function OrderAutomationDashboard() {
  const { user } = useUser();
  const location = useLocation();
  const isAdmin = user?.role === 'admin';

  const [dateFrom, setDateFrom] = useState(dateString(-29));
  const [dateTo, setDateTo] = useState(dateString(0));
  const [overview, setOverview] = useState<OrderAutomationOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [deliveryFile, setDeliveryFile] = useState<File | null>(null);
  const [templateFile, setTemplateFile] = useState<File | null>(null);
  const [processing, setProcessing] = useState(false);
  const [processError, setProcessError] = useState<string | null>(null);
  const [lastDownload, setLastDownload] = useState<{ filename: string; summary: string; syncStatus: string } | null>(null);

  const [replyFiles, setReplyFiles] = useState<File[]>([]);
  const [trackingDeliveryFile, setTrackingDeliveryFile] = useState<File | null>(null);
  const [trackingProcessing, setTrackingProcessing] = useState(false);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [lastTrackingDownload, setLastTrackingDownload] = useState<{ filename: string; summary: string } | null>(null);

  const [supplierMonitors, setSupplierMonitors] = useState<SupplierMonitorEntry[]>([]);
  const [supplierLoading, setSupplierLoading] = useState(false);
  const [supplierRefreshing, setSupplierRefreshing] = useState(false);
  const [supplierError, setSupplierError] = useState<string | null>(null);
  const [downloadingMonitorKey, setDownloadingMonitorKey] = useState<SupplierMonitorKey | null>(null);
  const [expandedMonitorKeys, setExpandedMonitorKeys] = useState<Partial<Record<SupplierMonitorKey, boolean>>>({});
  const [hiddenSupplierMonitorKeys, setHiddenSupplierMonitorKeys] = useState<SupplierMonitorKey[]>(readHiddenSupplierMonitorKeys);

  async function loadOverview(isRefreshing = false) {
    if (isRefreshing) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const next = await getOrderAutomationOverview(dateFrom, dateTo);
      setOverview(next);
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : '대시보드 데이터를 불러오지 못했습니다.';
      setError(message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadSupplierMonitors(isRefreshing = false) {
    if (!isAdmin) return;

    if (isRefreshing) {
      setSupplierRefreshing(true);
    } else {
      setSupplierLoading(true);
    }

    try {
      const results = await Promise.all(
        activeSupplierMonitorKeys().map(async (config) => {
          try {
            return {
              ok: true as const,
              value: {
                key: config.key,
                accent: config.accent,
                data: await fetchSupplierPriceMonitor(config.key),
              },
            };
          } catch (reason) {
            return {
              ok: false as const,
              key: config.key,
              reason,
            };
          }
        }),
      );

      const fulfilled = results
        .filter((result): result is { ok: true; value: SupplierMonitorEntry } => result.ok)
        .map((result) => result.value);

      const rejected = results
        .filter((result): result is { ok: false; key: SupplierMonitorKey; reason: unknown } => !result.ok);

      setSupplierMonitors(fulfilled);

      if (rejected.length && fulfilled.length) {
        const labels = rejected.map((result) => SUPPLIER_MONITOR_LABELS[result.key]).join(', ');
        setSupplierError(`일부 공급가 비교만 불러왔습니다: ${labels}`);
      } else if (rejected.length) {
        const reason = rejected[0];
        setSupplierError(reason.reason instanceof Error ? reason.reason.message : '공급가 비교 데이터를 불러오지 못했습니다.');
      } else {
        setSupplierError(null);
      }
    } finally {
      setSupplierLoading(false);
      setSupplierRefreshing(false);
    }
  }

  useEffect(() => {
    loadOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (isAdmin) {
      loadSupplierMonitors();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  useEffect(() => {
    if (location.hash !== '#margin-defense') return;
    window.setTimeout(() => {
      document.getElementById('margin-defense')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      });
    }, 120);
  }, [location.hash]);

  const trendData = useMemo(
    () =>
      (overview?.trend ?? []).map((row) => ({
        label: formatDayLabel(row.ymd),
        quantity: row.total_qty,
      })),
    [overview],
  );

  const optionChartData = useMemo(
    () =>
      (overview?.top_options ?? []).map((row) => ({
        label: row.supply_option_name || row.product_name,
        quantity: row.total_qty,
      })),
    [overview],
  );

  const hiddenSupplierMonitorSet = useMemo(
    () => new Set<SupplierMonitorKey>(hiddenSupplierMonitorKeys),
    [hiddenSupplierMonitorKeys],
  );

  const visibleSupplierMonitors = useMemo(
    () => supplierMonitors.filter((monitor) => !hiddenSupplierMonitorSet.has(monitor.key)),
    [hiddenSupplierMonitorSet, supplierMonitors],
  );

  const combinedMonitorRows = useMemo<CombinedMonitorRow[]>(
    () =>
      visibleSupplierMonitors
        .flatMap((monitor) =>
          monitor.data.rows.map((row) => ({
            monitorKey: monitor.key,
            accent: monitor.accent,
            title: monitor.data.title,
            supplierName: monitor.data.supplier_name,
            productName: monitor.data.product_name,
            checkedAt: monitor.data.checked_at,
            optionName: row.option_name,
            supplierOptionName: row.supplier_option_name,
            cell: row.cell,
            previousPrice: row.spreadsheet_price,
            currentPrice: row.supplier_price,
            diff: row.diff,
            signal: row.signal,
            signalLabel: row.signal_label,
            margin: row.margin,
            marginNegative: Boolean(row.margin_negative),
          })),
        )
        .sort((left, right) => {
          if (left.signal === 'same' && right.signal !== 'same') return 1;
          if (left.signal !== 'same' && right.signal === 'same') return -1;
          return Math.abs(right.diff) - Math.abs(left.diff);
        }),
    [visibleSupplierMonitors],
  );

  const supplierSummary = useMemo(() => {
    const latestCheckedAt = visibleSupplierMonitors
      .map((monitor) => new Date(monitor.data.checked_at).getTime())
      .filter((value) => !Number.isNaN(value))
      .sort((left, right) => right - left)[0];

    return {
      productCount: visibleSupplierMonitors.length,
      optionCount: combinedMonitorRows.length,
      upCount: combinedMonitorRows.filter((row) => row.signal === 'blue').length,
      downCount: combinedMonitorRows.filter((row) => row.signal === 'red').length,
      sameCount: combinedMonitorRows.filter((row) => row.signal === 'same').length,
      negativeMarginCount: combinedMonitorRows.filter((row) => row.marginNegative).length,
      latestCheckedAt: latestCheckedAt ? new Date(latestCheckedAt).toISOString() : null,
    };
  }, [combinedMonitorRows, visibleSupplierMonitors]);

  const monitorGroups = useMemo<MonitorGroup[]>(
    () =>
      visibleSupplierMonitors
        .map((monitor) => {
          const rows: CombinedMonitorRow[] = monitor.data.rows
            .map((row) => ({
              monitorKey: monitor.key,
              accent: monitor.accent,
              title: monitor.data.title,
              supplierName: monitor.data.supplier_name,
              productName: monitor.data.product_name,
              checkedAt: monitor.data.checked_at,
              optionName: row.option_name,
              supplierOptionName: row.supplier_option_name,
              cell: row.cell,
              previousPrice: row.spreadsheet_price,
              currentPrice: row.supplier_price,
              diff: row.diff,
              signal: row.signal,
              signalLabel: row.signal_label,
              margin: row.margin,
              marginNegative: Boolean(row.margin_negative),
            }))
            .sort(sortByOptionWeight);

          if (!rows.length) return null;

          const group: MonitorGroup = {
            key: monitor.key,
            accent: monitor.accent,
            title: monitor.data.title,
            supplierName: monitor.data.supplier_name,
            productName: monitor.data.product_name,
            checkedAt: monitor.data.checked_at,
            rows,
            representative: rows[0],
            upCount: rows.filter((row) => row.signal === 'blue').length,
            downCount: rows.filter((row) => row.signal === 'red').length,
            sameCount: rows.filter((row) => row.signal === 'same').length,
            negativeMarginCount: rows.filter((row) => row.marginNegative).length,
          };

          return group;
        })
        .filter((group): group is MonitorGroup => Boolean(group)),
    [visibleSupplierMonitors],
  );

  async function handleProcess() {
    if (!deliveryFile) {
      setProcessError('DeliveryList 파일을 먼저 선택해 주세요.');
      return;
    }

    setProcessing(true);
    setProcessError(null);

    try {
      const result = await processDanharuOrder(deliveryFile, templateFile);
      downloadBlob(result.blob, result.filename);
      setLastDownload({
        filename: result.filename,
        summary: summarizeOrderStats(result.stats),
        syncStatus: result.sync_status,
      });
      setDeliveryFile(null);
      setTemplateFile(null);
      await loadOverview(true);
    } catch (processLoadError) {
      const message = processLoadError instanceof Error ? processLoadError.message : '발주서 생성에 실패했습니다.';
      setProcessError(message);
    } finally {
      setProcessing(false);
    }
  }

  async function handleTrackingProcess() {
    if (replyFiles.length === 0 || !trackingDeliveryFile) {
      setTrackingError('회신 파일(1개 이상)과 DeliveryList를 모두 선택해 주세요.');
      return;
    }

    setTrackingProcessing(true);
    setTrackingError(null);

    try {
      const result = await processDanharuTracking(replyFiles, trackingDeliveryFile);
      downloadBlob(result.blob, result.filename);
      setLastTrackingDownload({
        filename: result.filename,
        summary: summarizeTrackingStats(result.stats),
      });
      setReplyFiles([]);
      setTrackingDeliveryFile(null);
    } catch (trackingLoadError) {
      const message = trackingLoadError instanceof Error ? trackingLoadError.message : '송장번호 입력에 실패했습니다.';
      setTrackingError(message);
    } finally {
      setTrackingProcessing(false);
    }
  }

  async function handleDownloadMonitor(key: SupplierMonitorKey) {
    setDownloadingMonitorKey(key);
    try {
      const result = await downloadSupplierPriceMonitorWorkbook(key);

      downloadBlob(result.blob, result.filename);
      await loadSupplierMonitors(true);
    } catch (downloadError) {
      setSupplierError(downloadError instanceof Error ? downloadError.message : '비교 엑셀 생성에 실패했습니다.');
    } finally {
      setDownloadingMonitorKey(null);
    }
  }

  function updateHiddenSupplierMonitorKeys(nextKeys: SupplierMonitorKey[]) {
    setHiddenSupplierMonitorKeys(nextKeys);
    try {
      window.localStorage.setItem(HIDDEN_SUPPLIER_MONITORS_STORAGE_KEY, JSON.stringify(nextKeys));
    } catch {
      // 로컬 저장소를 사용할 수 없어도 화면 토글은 유지합니다.
    }
  }

  function toggleSupplierMonitorVisibility(key: SupplierMonitorKey) {
    const nextKeys = hiddenSupplierMonitorSet.has(key)
      ? hiddenSupplierMonitorKeys.filter((item) => item !== key)
      : [...hiddenSupplierMonitorKeys, key];
    updateHiddenSupplierMonitorKeys(nextKeys);
  }

  function toggleMonitorGroup(key: SupplierMonitorKey) {
    setExpandedMonitorKeys((current) => ({
      ...current,
      [key]: !current[key],
    }));
  }

  function scrollToMarginDefense() {
    document.getElementById('margin-defense')?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  }

  const totals = overview?.totals;

  return (
    <div className="relative isolate overflow-hidden">
      <div className="absolute inset-x-0 top-0 -z-10 h-80 bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.28),_transparent_40%),radial-gradient(circle_at_top_right,_rgba(16,185,129,0.18),_transparent_35%),linear-gradient(180deg,_#fffaf0_0%,_#f8fafc_65%)]" />

      <section className="grid gap-6 lg:grid-cols-[1.4fr_0.9fr]">
        <div className="rounded-[28px] border border-amber-100 bg-white/90 p-7 shadow-[0_25px_80px_-35px_rgba(15,23,42,0.35)] backdrop-blur">
          <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-amber-700">
            <span className="rounded-full bg-amber-100 px-3 py-1">단하루 전용</span>
            <span className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-700">발주 생성 + 송장 입력</span>
          </div>

          <div className="mt-5 max-w-2xl">
            <h1 className="text-3xl font-black tracking-tight text-slate-900 sm:text-4xl">
              단하루 발주를 만들고
              <br />
              송장 흐름까지 가볍게 한 화면에서 관리
            </h1>
            <p className="mt-4 text-sm leading-6 text-slate-600 sm:text-base">
              DeliveryList를 올리면 단하루 발주서를 생성하고, 필요한 배치 이력만 간단하게 남깁니다.
              거래처 회신 파일의 송장번호는 다시 DeliveryList에 바로 반영할 수 있습니다.
            </p>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-3">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">누적 배치</p>
              <p className="mt-3 text-2xl font-black text-slate-900">{totals ? totals.batch_count.toLocaleString('ko-KR') : '-'}</p>
              <p className="mt-1 text-xs text-slate-500">발주 생성 이력</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">발주 수량</p>
              <p className="mt-3 text-2xl font-black text-slate-900">{totals ? totals.quantity.toLocaleString('ko-KR') : '-'}</p>
              <p className="mt-1 text-xs text-slate-500">선택 기간 기준 총 발주 수량</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">활성 옵션</p>
              <p className="mt-3 text-2xl font-black text-slate-900">{totals ? totals.unique_options.toLocaleString('ko-KR') : '-'}</p>
              <p className="mt-1 text-xs text-slate-500">배치에 포함된 공급 옵션 수</p>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              to={isAdmin ? '/orders' : '/my/process'}
              className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              {isAdmin ? '기존 발주 도구 보기' : '내 발주 자동화 시작'}
              <ArrowRight size={15} />
            </Link>
            {isAdmin && (
              <button
                type="button"
                onClick={scrollToMarginDefense}
                className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-5 py-3 text-sm font-black text-emerald-700 transition hover:border-emerald-300 hover:bg-emerald-100"
              >
                마진 방어
                <ArrowRight size={15} />
              </button>
            )}
          </div>
        </div>

        <div className="grid gap-6">
          <div className="rounded-[28px] border border-slate-200 bg-slate-950 p-6 text-white shadow-[0_25px_80px_-35px_rgba(15,23,42,0.6)]">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">Quick Run</p>
                <h2 className="mt-2 text-2xl font-black">단하루 발주 업로드</h2>
              </div>
              <div className="rounded-2xl bg-white/10 p-3">
                <Rocket size={20} className="text-amber-300" />
              </div>
            </div>

            <div className="mt-6 space-y-4">
              <UploadField
                title="DeliveryList 업로드"
                description="쿠팡 DeliveryList 원본 엑셀"
                tone="amber"
                file={deliveryFile}
                onChange={setDeliveryFile}
              />
              <UploadField
                title="양식 교체 (선택)"
                description="기본 단하루 양식 대신 별도 템플릿 사용"
                tone="sky"
                file={templateFile}
                onChange={setTemplateFile}
              />
            </div>

            <button
              onClick={handleProcess}
              disabled={processing}
              className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-amber-400 px-5 py-3 text-sm font-black text-slate-900 transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:bg-amber-200"
            >
              {processing ? <RefreshCw size={16} className="animate-spin" /> : <Rocket size={16} />}
              발주서 생성
            </button>

            <p className="mt-3 text-xs leading-5 text-slate-300">
              생성되는 단하루 발주서의 M열은 거래처가 송장번호를 입력할 수 있도록 비워 둡니다.
            </p>

            {processError && (
              <div className="mt-4 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                {processError}
              </div>
            )}

            {lastDownload && (
              <div className="mt-4 rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-3 text-sm">
                <p className="font-semibold text-emerald-200">{lastDownload.filename}</p>
                <p className="mt-1 text-emerald-100">{lastDownload.summary}</p>
                <p className="mt-1 text-xs text-emerald-200">저장 상태: {syncStatusLabel(lastDownload.syncStatus)}</p>
              </div>
            )}
          </div>

          <div className="rounded-[28px] border border-slate-200 bg-slate-900 p-6 text-white shadow-[0_25px_80px_-35px_rgba(15,23,42,0.45)]">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">Tracking Input</p>
                <h2 className="mt-2 text-2xl font-black">송장번호 입력</h2>
              </div>
              <div className="rounded-2xl bg-white/10 p-3">
                <FileSpreadsheet size={20} className="text-sky-300" />
              </div>
            </div>

            <div className="mt-6 space-y-4">
              <MultiUploadField
                title="회신/송장 파일"
                description="단하루 회신, Orderlist, 아이티소프트 회신 등 여러 파일을 한 번에 추가"
                tone="sky"
                files={replyFiles}
                onChange={setReplyFiles}
              />
              <UploadField
                title="DeliveryList 원본"
                description="송장번호를 채워 넣을 쿠팡 DeliveryList"
                tone="emerald"
                file={trackingDeliveryFile}
                onChange={setTrackingDeliveryFile}
              />
            </div>

            <button
              onClick={handleTrackingProcess}
              disabled={trackingProcessing || replyFiles.length === 0 || !trackingDeliveryFile}
              className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-sky-400 px-5 py-3 text-sm font-black text-slate-950 transition hover:bg-sky-300 disabled:cursor-not-allowed disabled:bg-sky-200"
            >
              {trackingProcessing ? <RefreshCw size={16} className="animate-spin" /> : <Upload size={16} />}
              DeliveryList에 송장번호 입력
            </button>

            {trackingError && (
              <div className="mt-4 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                {trackingError}
              </div>
            )}

            {lastTrackingDownload && (
              <div className="mt-4 rounded-2xl border border-sky-400/20 bg-sky-500/10 px-4 py-3 text-sm">
                <p className="font-semibold text-sky-100">{lastTrackingDownload.filename}</p>
                <p className="mt-1 text-sky-200">{lastTrackingDownload.summary}</p>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="mt-6 grid gap-4 xl:grid-cols-5">
        <MetricCard
          label="선택 기간 주문 건수"
          value={totals ? totals.order_count.toLocaleString('ko-KR') : '-'}
          hint="배치에 포함된 주문 건수"
          icon={Layers3}
        />
        <MetricCard
          label="배치당 평균 주문"
          value={totals ? totals.avg_orders_per_batch.toLocaleString('ko-KR') : '-'}
          hint="업로드 한 번당 처리되는 평균 건수"
          icon={Boxes}
        />
        <MetricCard
          label="운영 일수"
          value={totals ? totals.active_days.toLocaleString('ko-KR') : '-'}
          hint="실제로 발주가 생성된 날짜 수"
          icon={BarChart3}
        />
        <MetricCard
          label="동기화 완료"
          value={totals ? totals.synced_batches.toLocaleString('ko-KR') : '-'}
          hint={overview?.supabase_enabled ? 'Supabase 미러링까지 완료된 배치' : '현재는 로컬 저장 모드'}
          icon={Database}
        />
        <MetricCard
          label="대기 / 실패"
          value={totals ? `${totals.sync_pending}/${totals.sync_errors}` : '-'}
          hint="pending / error"
          icon={RefreshCw}
        />
      </section>

      {isAdmin && (
        <section id="margin-defense" className="mt-6 scroll-mt-8 rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl">
              <div className="inline-flex items-center gap-2 rounded-full bg-emerald-900 px-3 py-1 text-xs font-bold uppercase tracking-[0.16em] text-white">
                <PackageSearch size={14} />
                마진 방어
              </div>
              <h2 className="mt-4 text-2xl font-black text-slate-900">공급가 변동을 잡아 마진을 바로 방어</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">
                전날 저장된 거래처 공급가와 오늘 거래처 공급가를 비교합니다. 실제 거래처가 바뀐 옵션만 마진 방어 알림에 쌓입니다.
              </p>
            </div>
            <button
              onClick={() => loadSupplierMonitors(true)}
              disabled={supplierLoading || supplierRefreshing}
              className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <RefreshCw size={15} className={supplierRefreshing ? 'animate-spin' : ''} />
              공급가 다시 확인
            </button>
          </div>

          <div className="mt-5 rounded-3xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-black text-slate-900">표시 설정</p>
                <p className="mt-1 text-xs text-slate-500">
                  품절 또는 운영 중단 상품은 숨김으로 두면 카드와 표에서 제외됩니다.
                </p>
              </div>
              {hiddenSupplierMonitorKeys.length > 0 && (
                <span className="rounded-full bg-white px-3 py-1 text-xs font-bold text-slate-500">
                  숨김 {hiddenSupplierMonitorKeys.length}개
                </span>
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {SUPPLIER_MONITOR_KEYS.map((config) => {
                const hidden = hiddenSupplierMonitorSet.has(config.key);
                return (
                  <button
                    key={config.key}
                    type="button"
                    onClick={() => toggleSupplierMonitorVisibility(config.key)}
                    className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-bold transition ${
                      hidden
                        ? 'border-slate-200 bg-white text-slate-400 hover:text-slate-600'
                        : 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                    }`}
                  >
                    <span>{SUPPLIER_MONITOR_LABELS[config.key]}</span>
                    <span className={`rounded-full px-2 py-0.5 ${hidden ? 'bg-slate-100' : 'bg-white/80'}`}>
                      {hidden ? '숨김' : '표시'}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-6">
            <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">관리 상품</p>
              <p className="mt-3 text-3xl font-black text-slate-900">{supplierSummary.productCount}</p>
              <p className="mt-2 text-xs text-slate-500">현재 표시 중인 공급가 카드 수</p>
            </div>
            <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">비교 옵션</p>
              <p className="mt-3 text-3xl font-black text-slate-900">{supplierSummary.optionCount}</p>
              <p className="mt-2 text-xs text-slate-500">같은 표에서 보는 전체 옵션 수</p>
            </div>
            <div className="rounded-3xl border border-blue-200 bg-blue-50 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">상승</p>
              <p className="mt-3 text-3xl font-black text-blue-700">{supplierSummary.upCount}</p>
              <p className="mt-2 text-xs text-blue-600">전일 대비 공급가가 오른 옵션</p>
            </div>
            <div className="rounded-3xl border border-rose-200 bg-rose-50 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-rose-600">하락</p>
              <p className="mt-3 text-3xl font-black text-rose-700">{supplierSummary.downCount}</p>
              <p className="mt-2 text-xs text-rose-600">전일 대비 공급가가 내린 옵션</p>
            </div>
            <div className="rounded-3xl border border-red-200 bg-red-50 p-5">
              <div className="flex items-center gap-2 text-red-700">
                <AlertTriangle size={16} />
                <p className="text-xs font-semibold uppercase tracking-[0.16em]">마진 경고</p>
              </div>
              <p className="mt-3 text-3xl font-black text-red-700">{supplierSummary.negativeMarginCount}</p>
              <p className="mt-2 text-xs text-red-600">수수료/공급가 반영 후 마이너스 옵션</p>
            </div>
            <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">마지막 점검</p>
              <p className="mt-3 text-lg font-black text-slate-900">
                {supplierSummary.latestCheckedAt ? formatDateTime(supplierSummary.latestCheckedAt) : '-'}
              </p>
              <p className="mt-2 text-xs text-slate-500">동일 옵션 {supplierSummary.sameCount}개 포함</p>
            </div>
          </div>

          {supplierError && (
            <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {supplierError}
            </div>
          )}

          {supplierLoading ? (
            <div className="mt-6 grid gap-4 lg:grid-cols-3">
              {[1, 2, 3].map((index) => (
                <div key={index} className="h-44 animate-pulse rounded-3xl bg-slate-100" />
              ))}
            </div>
          ) : (
            <>
              <div className="mt-6 grid gap-4 xl:grid-cols-3">
                {visibleSupplierMonitors.map((monitor) => (
                  <SupplierMonitorCard
                    key={monitor.key}
                    monitor={monitor}
                    downloading={downloadingMonitorKey === monitor.key}
                    onDownload={handleDownloadMonitor}
                  />
                ))}
                {visibleSupplierMonitors.length === 0 && (
                  <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-400 xl:col-span-3">
                    표시 중인 마진방어 상품이 없습니다. 표시 설정에서 상품을 켜 주세요.
                  </div>
                )}
              </div>

              <div className="mt-6 overflow-hidden rounded-3xl border border-slate-200">
                <div className="overflow-x-auto">
                  <table className="min-w-full bg-white text-sm">
                    <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
                      <tr>
                        <th className="px-4 py-3">상품</th>
                        <th className="px-4 py-3">거래처</th>
                        <th className="px-4 py-3">옵션</th>
                        <th className="px-4 py-3 text-right">전일가</th>
                        <th className="px-4 py-3 text-right">오늘가</th>
                        <th className="px-4 py-3 text-right">변동액</th>
                        <th className="px-4 py-3">상태</th>
                        <th className="px-4 py-3">기준</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monitorGroups.map((group) => {
                        const expanded = Boolean(expandedMonitorKeys[group.key]);
                        const representative = group.representative;

                        return (
                          <Fragment key={group.key}>
                            <tr className="border-t border-slate-100 bg-white align-top">
                              <td className="px-4 py-4">
                                <button
                                  type="button"
                                  onClick={() => toggleMonitorGroup(group.key)}
                                  aria-expanded={expanded}
                                  className="flex w-full items-start gap-3 text-left"
                                >
                                  <span className="mt-0.5 rounded-lg border border-slate-200 p-1 text-slate-500">
                                    {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                                  </span>
                                  <span className="flex flex-col gap-1">
                                    <span className="font-semibold text-slate-900">{group.productName}</span>
                                    <span className="text-xs text-slate-500">{group.rows.length}개 옵션</span>
                                  </span>
                                </button>
                              </td>
                              <td className="px-4 py-4">
                                <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${accentClass(group.accent)}`}>
                                  {group.supplierName}
                                </span>
                              </td>
                              <td className="px-4 py-4">
                                <div className="max-w-[360px]">
                                  <p className="font-medium text-slate-900">대표: {representative.optionName}</p>
                                  {representative.supplierOptionName && (
                                    <p className="mt-1 text-xs leading-5 text-slate-500">{representative.supplierOptionName}</p>
                                  )}
                                </div>
                              </td>
                              <td className="px-4 py-4 text-right font-medium text-slate-600">
                                {formatCurrency(representative.previousPrice)}
                              </td>
                              <td className="px-4 py-4 text-right font-semibold text-slate-900">
                                {formatCurrency(representative.currentPrice)}
                              </td>
                              <td
                                className={`px-4 py-4 text-right font-black ${
                                  representative.signal === 'blue'
                                    ? 'text-blue-700'
                                    : representative.signal === 'red'
                                      ? 'text-rose-700'
                                      : 'text-slate-600'
                                }`}
                              >
                                {diffPrefix(representative.signal)}
                                {formatCurrency(Math.abs(representative.diff))}
                              </td>
                              <td className="px-4 py-4">
                                <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${signalClass(representative.signal)}`}>
                                  {groupStatusLabel(group)}
                                </span>
                                {representative.marginNegative && (
                                  <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs font-bold text-red-700">
                                    <AlertTriangle size={13} />
                                    마진 {formatCurrency(representative.margin ?? 0)}
                                  </div>
                                )}
                              </td>
                              <td className="px-4 py-4 text-xs text-slate-500">
                                <div>{representative.cell}</div>
                                <div className="mt-1">{formatDateTime(group.checkedAt)}</div>
                              </td>
                            </tr>

                            {expanded &&
                              group.rows.map((row) => (
                                <tr key={`${row.monitorKey}-${row.cell}-${row.optionName}`} className="border-t border-slate-100 bg-slate-50/70 align-top">
                                  <td className="px-4 py-3 text-xs font-semibold text-slate-400">
                                    옵션
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${accentClass(row.accent)}`}>
                                      {row.supplierName}
                                    </span>
                                  </td>
                                  <td className="px-4 py-3">
                                    <div className="max-w-[380px]">
                                      <p className="font-medium text-slate-900">{row.optionName}</p>
                                      {row.supplierOptionName && (
                                        <p className="mt-1 text-xs leading-5 text-slate-500">{row.supplierOptionName}</p>
                                      )}
                                    </div>
                                  </td>
                                  <td className="px-4 py-3 text-right font-medium text-slate-600">
                                    {formatCurrency(row.previousPrice)}
                                  </td>
                                  <td className="px-4 py-3 text-right font-semibold text-slate-900">
                                    {formatCurrency(row.currentPrice)}
                                  </td>
                                  <td
                                    className={`px-4 py-3 text-right font-black ${
                                      row.signal === 'blue'
                                        ? 'text-blue-700'
                                        : row.signal === 'red'
                                          ? 'text-rose-700'
                                          : 'text-slate-600'
                                    }`}
                                  >
                                    {diffPrefix(row.signal)}
                                    {formatCurrency(Math.abs(row.diff))}
                                  </td>
                                  <td className="px-4 py-3">
                                    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${signalClass(row.signal)}`}>
                                      {signalLabel(row.signal)}
                                    </span>
                                    {row.marginNegative && (
                                      <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs font-bold text-red-700">
                                        <AlertTriangle size={13} />
                                        마진 {formatCurrency(row.margin ?? 0)}
                                      </div>
                                    )}
                                  </td>
                                  <td className="px-4 py-3 text-xs text-slate-500">
                                    <div>{row.cell}</div>
                                    <div className="mt-1">{formatDateTime(row.checkedAt)}</div>
                                  </td>
                                </tr>
                              ))}
                          </Fragment>
                        );
                      })}
                      {!monitorGroups.length && (
                        <tr>
                          <td colSpan={8} className="px-4 py-10 text-center text-sm text-slate-400">
                            아직 불러온 공급가 비교 결과가 없습니다.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </section>
      )}

      <section className="mt-6 rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Range</p>
            <h2 className="mt-2 text-2xl font-black text-slate-900">발주 흐름 추적</h2>
            <p className="mt-2 text-sm text-slate-500">기간을 바꾸면 발주 배치 흐름과 상위 공급 옵션을 바로 확인할 수 있습니다.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700"
            />
            <input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700"
            />
            <button
              onClick={() => loadOverview(true)}
              disabled={refreshing}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
            >
              <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
              새로고침
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="mt-10 grid gap-4 lg:grid-cols-2">
            <div className="h-80 animate-pulse rounded-3xl bg-slate-100" />
            <div className="h-80 animate-pulse rounded-3xl bg-slate-100" />
          </div>
        ) : (
          <div className="mt-8 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
            <div className="rounded-3xl border border-slate-100 bg-slate-50 p-5">
              <h3 className="text-lg font-black text-slate-900">날짜별 발주 수량</h3>
              <p className="text-sm text-slate-500">배치별 총 수량을 날짜 기준으로 집계합니다.</p>
              <div className="mt-4 h-72">
                {trendData.length === 0 ? (
                  <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-200 text-sm text-slate-400">
                    아직 집계된 배치가 없습니다.
                  </div>
                ) : (
                  <ResponsiveContainer>
                    <AreaChart data={trendData}>
                      <defs>
                        <linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1">
                          <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.35} />
                          <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                      <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Area type="monotone" dataKey="quantity" stroke="#d97706" fill="url(#trendFill)" strokeWidth={2.5} />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-slate-100 bg-slate-50 p-5">
              <h3 className="text-lg font-black text-slate-900">상위 공급 옵션</h3>
              <p className="text-sm text-slate-500">가장 많이 발주된 옵션을 바로 봅니다.</p>
              <div className="mt-4 h-72">
                {optionChartData.length === 0 ? (
                  <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-200 text-sm text-slate-400">
                    발주 배치가 아직 없습니다.
                  </div>
                ) : (
                  <ResponsiveContainer>
                    <BarChart data={optionChartData} layout="vertical" margin={{ left: 10, right: 10 }}>
                      <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                      <XAxis type="number" tick={{ fontSize: 11 }} />
                      <YAxis dataKey="label" type="category" width={140} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="quantity" fill="#0f766e" radius={[0, 8, 8, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="mt-6 grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Recent Activity</p>
            <h2 className="mt-2 text-2xl font-black text-slate-900">최근 발주 배치</h2>
          </div>

          <div className="mt-5 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="border-b border-slate-200 text-left text-xs uppercase tracking-[0.16em] text-slate-500">
                <tr>
                  <th className="pb-3 pr-4">배치명</th>
                  <th className="pb-3 pr-4">건수</th>
                  <th className="pb-3 pr-4">수량</th>
                  <th className="pb-3 pr-4">동기화</th>
                  <th className="pb-3">생성 시각</th>
                </tr>
              </thead>
              <tbody>
                {(overview?.recent_batches ?? []).map((batch) => (
                  <tr key={batch.id} className="border-b border-slate-100 align-top">
                    <td className="py-4 pr-4">
                      <p className="font-semibold text-slate-900">{batch.batch_name}</p>
                      <p className="mt-1 text-xs text-slate-500">{batch.output_filename}</p>
                    </td>
                    <td className="py-4 pr-4 text-slate-600">{batch.total_rows.toLocaleString('ko-KR')}</td>
                    <td className="py-4 pr-4 font-semibold text-slate-900">{batch.total_quantity.toLocaleString('ko-KR')}</td>
                    <td className="py-4 pr-4">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                          batch.sync_status === 'synced'
                            ? 'bg-emerald-100 text-emerald-700'
                            : batch.sync_status === 'error'
                              ? 'bg-rose-100 text-rose-700'
                              : 'bg-slate-100 text-slate-600'
                        }`}
                      >
                        {syncStatusLabel(batch.sync_status)}
                      </span>
                      {batch.sync_error && <p className="mt-1 max-w-xs text-[11px] text-rose-600">{batch.sync_error}</p>}
                    </td>
                    <td className="py-4 text-slate-500">{formatDateTime(batch.processed_at)}</td>
                  </tr>
                ))}
                {!overview?.recent_batches.length && !loading && (
                  <tr>
                    <td colSpan={5} className="py-10 text-center text-sm text-slate-400">
                      아직 생성된 배치가 없습니다.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-[28px] border border-slate-200 bg-slate-900 p-6 text-white shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-300">Playbook</p>
          <h2 className="mt-2 text-2xl font-black">운영 흐름</h2>
          <div className="mt-6 space-y-4">
            {[
              { title: '1. DeliveryList 업로드', body: '쿠팡 원본 엑셀만 올리면 단하루 양식으로 바로 변환됩니다.' },
              { title: '2. 배치 이력 기록', body: '발주서 파일명과 처리 건수만 가볍게 기록합니다.' },
              { title: '3. 송장번호 회신 반영', body: '회신 파일과 DeliveryList를 다시 올리면 E열 송장번호를 자동 입력합니다.' },
            ].map((step) => (
              <div key={step.title} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="font-semibold text-white">{step.title}</p>
                <p className="mt-1 text-sm leading-6 text-slate-300">{step.body}</p>
              </div>
            ))}
          </div>

          <div className="mt-6 grid gap-3">
            <Link
              to="/my/products"
              className="inline-flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              상품/옵션 매핑 관리
              <ArrowRight size={15} />
            </Link>
            <Link
              to={isAdmin ? '/orders' : '/my/process'}
              className="inline-flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              {isAdmin ? '기존 발주 자동화 도구' : '내 발주 자동화'}
              <ArrowRight size={15} />
            </Link>
            <a
              href="https://supabase.com"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              Supabase 연결 가이드
              <ArrowRight size={15} />
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
