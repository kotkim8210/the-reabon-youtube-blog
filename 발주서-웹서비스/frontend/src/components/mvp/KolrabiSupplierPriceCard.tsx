import { useEffect, useState } from 'react';
import { BellRing, Download, Loader2, Minus, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react';
import {
  downloadBlob,
  downloadKolrabiSupplierPriceMonitorWorkbook,
  fetchKolrabiSupplierPriceMonitor,
  type SupplierPriceMonitorData,
} from '../../api';

const signalStyle = {
  blue: {
    badge: 'bg-blue-50 text-blue-700 border-blue-200',
    row: 'border-blue-100 bg-blue-50/60',
    icon: TrendingUp,
    diffPrefix: '+',
  },
  red: {
    badge: 'bg-rose-50 text-rose-700 border-rose-200',
    row: 'border-rose-100 bg-rose-50/60',
    icon: TrendingDown,
    diffPrefix: '-',
  },
  same: {
    badge: 'bg-slate-100 text-slate-600 border-slate-200',
    row: 'border-slate-100 bg-slate-50',
    icon: Minus,
    diffPrefix: '',
  },
} as const;

function formatPrice(value: number) {
  return `₩${value.toLocaleString()}`;
}

function KolrabiSupplierPriceCard() {
  const [data, setData] = useState<SupplierPriceMonitorData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async (asRefresh = false) => {
    try {
      if (asRefresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      setError(null);
      setData(await fetchKolrabiSupplierPriceMonitor());
    } catch (e) {
      setError(e instanceof Error ? e.message : '콜라비 공급가 비교를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const downloadWorkbook = async () => {
    try {
      setDownloading(true);
      setError(null);
      const result = await downloadKolrabiSupplierPriceMonitorWorkbook();
      downloadBlob(result.blob, result.filename);
      if (result.stats) {
        setData(result.stats as unknown as SupplierPriceMonitorData);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '콜라비 비교 엑셀 다운로드에 실패했습니다.');
    } finally {
      setDownloading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <section className="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-600">
              <BellRing size={18} />
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.24em] text-emerald-600">Supplier Alert</p>
              <h3 className="text-xl font-black text-slate-900">콜라비 공급가 단가변경</h3>
            </div>
          </div>
          <p className="text-sm leading-6 text-slate-500">
            전날 저장된 제주다팜 콜라비 공급가와 오늘 관리자 사이트 공급가를 비교합니다.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => loadData(true)}
            disabled={loading || refreshing || downloading}
            className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-sm font-bold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
          >
            {refreshing ? <Loader2 size={16} className="mr-2 animate-spin" /> : <RefreshCw size={16} className="mr-2" />}
            단가 다시 확인
          </button>
          <button
            onClick={downloadWorkbook}
            disabled={loading || downloading}
            className="inline-flex items-center rounded-xl bg-emerald-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-emerald-500 disabled:opacity-50"
          >
            {downloading ? <Loader2 size={16} className="mr-2 animate-spin" /> : <Download size={16} className="mr-2" />}
            비교 엑셀 저장
          </button>
        </div>
      </div>

      {loading ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
          콜라비 공급가를 확인하는 중입니다.
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{error}</div>
      ) : data ? (
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">대상 상품</p>
              <p className="mt-2 text-lg font-black text-slate-900">{data.product_name}</p>
              <p className="mt-1 text-xs text-slate-500">거래처 {data.supplier_name}</p>
            </div>
            <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">전일 대비 상승</p>
              <p className="mt-2 text-3xl font-black text-blue-700">{data.blue_count}</p>
              <p className="mt-1 text-xs text-blue-600">공급가가 오른 옵션</p>
            </div>
            <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-rose-600">전일 대비 하락</p>
              <p className="mt-2 text-3xl font-black text-rose-700">{data.red_count}</p>
              <p className="mt-1 text-xs text-rose-600">공급가가 내린 옵션</p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">마지막 갱신</p>
              <p className="mt-2 text-base font-black text-slate-900">
                {new Date(data.checked_at).toLocaleString('ko-KR')}
              </p>
              <p className="mt-1 truncate text-xs text-slate-500">{data.output_filename}</p>
            </div>
          </div>

          <div className="space-y-3">
            {data.rows.map((row) => {
              const style = signalStyle[row.signal];
              const SignalIcon = style.icon;
              return (
                <div key={row.option_name} className={`rounded-2xl border p-4 ${style.row}`}>
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <div className="mb-1 flex items-center gap-2">
                        <p className="font-bold text-slate-900">{row.option_name}</p>
                        <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-bold ${style.badge}`}>
                          <SignalIcon size={12} className="mr-1" />
                          {row.signal_label}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500">소싱현황 시트 {row.cell} 셀에 최신 공급가로 저장됩니다.</p>
                    </div>
                    <div className="grid grid-cols-3 gap-3 text-sm md:min-w-[360px]">
                      <div className="rounded-xl bg-white/80 p-3">
                        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">전일 공급가</p>
                        <p className="mt-1 font-black text-slate-800">{formatPrice(row.spreadsheet_price)}</p>
                      </div>
                      <div className="rounded-xl bg-white/80 p-3">
                        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">현재 공급가</p>
                        <p className="mt-1 font-black text-slate-800">{formatPrice(row.supplier_price)}</p>
                      </div>
                      <div className="rounded-xl bg-white/80 p-3">
                        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400">변동폭</p>
                        <p className={`mt-1 font-black ${row.signal === 'blue' ? 'text-blue-700' : row.signal === 'red' ? 'text-rose-700' : 'text-slate-700'}`}>
                          {style.diffPrefix}
                          {formatPrice(Math.abs(row.diff))}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default KolrabiSupplierPriceCard;
