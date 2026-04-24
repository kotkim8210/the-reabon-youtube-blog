import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
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
  ArrowRight,
  BarChart3,
  Boxes,
  Database,
  FileSpreadsheet,
  Layers3,
  RefreshCw,
  Rocket,
  Upload,
} from 'lucide-react';

import {
  downloadBlob,
  getOrderAutomationOverview,
  processDanharuOrder,
  processDanharuTracking,
  type OrderAutomationOverview,
} from '../api';

function dateString(offsetDays = 0): string {
  const current = new Date();
  current.setDate(current.getDate() + offsetDays);
  return current.toISOString().slice(0, 10);
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

function summarizeOrderStats(stats?: Record<string, unknown> | null): string {
  if (!stats) return '';
  const rows = typeof stats.total_rows === 'number' ? stats.total_rows : 0;
  const quantity = typeof stats.total_quantity === 'number' ? stats.total_quantity : 0;
  return `${rows.toLocaleString()}건 / ${quantity.toLocaleString()}개`;
}

function summarizeTrackingStats(stats?: Record<string, unknown> | null): string {
  if (!stats) return '';
  const filled = typeof stats.filled === 'number' ? stats.filled : 0;
  const skipped = typeof stats.skipped === 'number' ? stats.skipped : 0;
  return `${filled.toLocaleString()}건 입력 / ${skipped.toLocaleString()}건 미매칭`;
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

export default function OrderAutomationDashboard() {
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

  const [replyFile, setReplyFile] = useState<File | null>(null);
  const [trackingDeliveryFile, setTrackingDeliveryFile] = useState<File | null>(null);
  const [trackingProcessing, setTrackingProcessing] = useState(false);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [lastTrackingDownload, setLastTrackingDownload] = useState<{ filename: string; summary: string } | null>(null);

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

  useEffect(() => {
    loadOverview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  async function handleProcess() {
    if (!deliveryFile) {
      setProcessError('DeliveryList 파일을 먼저 선택해주세요.');
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
      const message = processLoadError instanceof Error ? processLoadError.message : '발주서를 생성하지 못했습니다.';
      setProcessError(message);
    } finally {
      setProcessing(false);
    }
  }

  async function handleTrackingProcess() {
    if (!replyFile || !trackingDeliveryFile) {
      setTrackingError('회신 파일과 DeliveryList를 모두 선택해주세요.');
      return;
    }

    setTrackingProcessing(true);
    setTrackingError(null);

    try {
      const result = await processDanharuTracking(replyFile, trackingDeliveryFile);
      downloadBlob(result.blob, result.filename);
      setLastTrackingDownload({
        filename: result.filename,
        summary: summarizeTrackingStats(result.stats),
      });
      setReplyFile(null);
      setTrackingDeliveryFile(null);
    } catch (trackingLoadError) {
      const message = trackingLoadError instanceof Error ? trackingLoadError.message : '운송장번호를 입력하지 못했습니다.';
      setTrackingError(message);
    } finally {
      setTrackingProcessing(false);
    }
  }

  const totals = overview?.totals;

  return (
    <div className="relative isolate overflow-hidden">
      <div className="absolute inset-x-0 top-0 -z-10 h-80 bg-[radial-gradient(circle_at_top_left,_rgba(251,191,36,0.28),_transparent_40%),radial-gradient(circle_at_top_right,_rgba(16,185,129,0.18),_transparent_35%),linear-gradient(180deg,_#fffaf0_0%,_#f8fafc_65%)]" />

      <section className="grid gap-6 lg:grid-cols-[1.4fr_0.9fr]">
        <div className="rounded-[28px] border border-amber-100 bg-white/90 p-7 shadow-[0_25px_80px_-35px_rgba(15,23,42,0.35)] backdrop-blur">
          <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-amber-700">
            <span className="rounded-full bg-amber-100 px-3 py-1">단하루 전용</span>
            <span className="rounded-full bg-emerald-100 px-3 py-1 text-emerald-700">발주 생성 + 판매 추적 + 송장 입력</span>
          </div>

          <div className="mt-5 max-w-2xl">
            <h1 className="text-3xl font-black tracking-tight text-slate-900 sm:text-4xl">
              단하루 발주서를 만들고
              <br />
              판매 수량과 송장 흐름까지 한 화면에서 관리
            </h1>
            <p className="mt-4 text-sm leading-6 text-slate-600 sm:text-base">
              DeliveryList를 올리면 단하루 발주서를 생성하고, 같은 순간 배치 이력과 옵션별 판매 수량을 기록합니다.
              거래처가 회신한 단하루 파일의 M열 송장번호도 다시 DeliveryList에 바로 반영할 수 있습니다.
            </p>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-3">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">누적 배치</p>
              <p className="mt-3 text-2xl font-black text-slate-900">{totals ? totals.batch_count.toLocaleString() : '-'}</p>
              <p className="mt-1 text-xs text-slate-500">발주 생성 이력</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">판매 수량</p>
              <p className="mt-3 text-2xl font-black text-slate-900">{totals ? totals.quantity.toLocaleString() : '-'}</p>
              <p className="mt-1 text-xs text-slate-500">선택 기간 기준 총 판매 개수</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">옵션 다양도</p>
              <p className="mt-3 text-2xl font-black text-slate-900">{totals ? totals.unique_options.toLocaleString() : '-'}</p>
              <p className="mt-1 text-xs text-slate-500">추적 중인 공급 옵션 수</p>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              to="/orders"
              className="inline-flex items-center gap-2 rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800"
            >
              기존 발주 도구 보기
              <ArrowRight size={15} />
            </Link>
            <Link
              to="/sales"
              className="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:border-slate-400"
            >
              판매 대시보드 열기
            </Link>
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
              발주서 생성하고 판매 로그 적재
            </button>

            <p className="mt-3 text-xs leading-5 text-slate-300">
              생성되는 단하루 파일의 M열은 회신용 송장번호 입력 칸으로 비워집니다.
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
                <p className="mt-1 text-xs text-emerald-200">Supabase 상태: {lastDownload.syncStatus}</p>
              </div>
            )}
          </div>

          <div className="rounded-[28px] border border-slate-200 bg-slate-900 p-6 text-white shadow-[0_25px_80px_-35px_rgba(15,23,42,0.45)]">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-300">Tracking Input</p>
                <h2 className="mt-2 text-2xl font-black">운송장번호 입력</h2>
              </div>
              <div className="rounded-2xl bg-white/10 p-3">
                <FileSpreadsheet size={20} className="text-sky-300" />
              </div>
            </div>

            <div className="mt-6 space-y-4">
              <UploadField
                title="단하루 회신 파일"
                description="M열에 송장번호가 입력된 회신 엑셀"
                tone="sky"
                file={replyFile}
                onChange={setReplyFile}
              />
              <UploadField
                title="DeliveryList 원본"
                description="운송장번호를 채워 넣을 쿠팡 DeliveryList"
                tone="emerald"
                file={trackingDeliveryFile}
                onChange={setTrackingDeliveryFile}
              />
            </div>

            <button
              onClick={handleTrackingProcess}
              disabled={trackingProcessing}
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
        {[
          {
            label: '선택 기간 주문 건수',
            value: totals ? totals.order_count.toLocaleString() : '-',
            hint: '배치에 포함된 주문 건수',
            icon: Layers3,
          },
          {
            label: '배치당 평균 주문',
            value: totals ? totals.avg_orders_per_batch.toLocaleString() : '-',
            hint: '업로드 1회당 처리되는 평균 건수',
            icon: Boxes,
          },
          {
            label: '운영 일수',
            value: totals ? totals.active_days.toLocaleString() : '-',
            hint: '실제로 발주가 생성된 날짜 수',
            icon: BarChart3,
          },
          {
            label: '동기화 완료',
            value: totals ? totals.synced_batches.toLocaleString() : '-',
            hint: overview?.supabase_enabled ? 'Supabase로 반영 완료된 배치' : '현재는 로컬 저장 모드',
            icon: Database,
          },
          {
            label: '대기 / 실패',
            value: totals ? `${totals.sync_pending}/${totals.sync_errors}` : '-',
            hint: 'pending / error',
            icon: RefreshCw,
          },
        ].map((card) => (
          <article key={card.label} className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{card.label}</p>
              <card.icon size={18} className="text-slate-400" />
            </div>
            <p className="mt-4 text-3xl font-black tracking-tight text-slate-900">{card.value}</p>
            <p className="mt-2 text-xs leading-5 text-slate-500">{card.hint}</p>
          </article>
        ))}
      </section>

      <section className="mt-6 rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Range</p>
            <h2 className="mt-2 text-2xl font-black text-slate-900">발주 흐름 추적</h2>
            <p className="mt-2 text-sm text-slate-500">기간을 바꾸면 발주량과 상위 옵션 판매 흐름을 바로 확인할 수 있습니다.</p>
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
              <h3 className="text-lg font-black text-slate-900">일자별 판매 수량</h3>
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
              <p className="text-sm text-slate-500">가장 많이 판매된 옵션을 바로 볼 수 있습니다.</p>
              <div className="mt-4 h-72">
                {optionChartData.length === 0 ? (
                  <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-200 text-sm text-slate-400">
                    판매 로그가 아직 없습니다.
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
                    <td className="py-4 pr-4 text-slate-600">{batch.total_rows.toLocaleString()}</td>
                    <td className="py-4 pr-4 font-semibold text-slate-900">{batch.total_quantity.toLocaleString()}</td>
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
                        {batch.sync_status}
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
              { title: '2. 회신 파일 M열 입력', body: '거래처는 단하루 발주서의 M열에 송장번호만 입력해서 보내면 됩니다.' },
              { title: '3. DeliveryList에 반영', body: '회신 파일과 원본 DeliveryList를 함께 올리면 E열에 송장번호만 자동 입력됩니다.' },
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
              to="/orders"
              className="inline-flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              기존 발주 자동화 도구
              <ArrowRight size={15} />
            </Link>
            <a
              href="https://supabase.com"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              Supabase 연결 가이드 준비됨
              <ArrowRight size={15} />
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
