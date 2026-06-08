import { useEffect, useState } from 'react';
import {
  AlertCircle,
  BellRing,
  ChevronRight,
  Clock,
  Download,
  Loader2,
  MessageSquare,
  Minus,
  Package,
  RefreshCw,
  Shield,
  ShoppingCart,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import {
  downloadBlob,
  downloadMyeongiSupplierPriceMonitorWorkbook,
  fetchDashboardSummary,
  fetchInventoryAlerts,
  fetchMe,
  fetchMyeongiSupplierPriceMonitor,
  fetchRecentOrders,
  fetchRiskScores,
  refreshDashboardData,
  type DashboardSummaryData,
  type InventoryAlertData,
  type OrderData,
  type RiskScoreData,
  type SupplierPriceMonitorData,
} from '../../api';
import StatusCard from './StatusCard';
import ChamoeAltteulSupplierPriceCard from './ChamoeAltteulSupplierPriceCard';
import KolrabiSupplierPriceCard from './KolrabiSupplierPriceCard';
import { CS_INQUIRIES, INVENTORY_ALERTS, MARKET_SCORES, RECENT_ORDERS } from './mockData';

function SkeletonCard() {
  return (
    <div className="p-5 rounded-2xl border-2 border-slate-200 bg-slate-50 animate-pulse">
      <div className="h-4 w-3/4 rounded bg-slate-200 mb-4" />
      <div className="h-8 w-1/2 rounded bg-slate-200 mb-4" />
      <div className="h-3 w-full rounded bg-slate-200 mb-2" />
      <div className="h-3 w-2/3 rounded bg-slate-200" />
    </div>
  );
}

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

function marketBadgeClass(market: string) {
  if (market.includes('쿠팡')) return 'bg-blue-600 text-white';
  if (market.includes('네이버')) return 'bg-emerald-600 text-white';
  if (market.includes('지마켓')) return 'bg-rose-500 text-white';
  if (market.includes('토스')) return 'bg-slate-800 text-white';
  return 'bg-slate-200 text-slate-700';
}

function statusClass(status: string) {
  if (status.includes('신규')) return 'text-blue-600 font-bold';
  if (status.includes('배송지연') || status.includes('확인')) return 'text-rose-500 font-bold';
  return 'text-slate-600';
}

function DashboardHome() {
  const [_risks, setRisks] = useState<RiskScoreData[]>([]);
  const [_orders, setOrders] = useState<OrderData[]>([]);
  const [_alerts, setAlerts] = useState<InventoryAlertData[]>([]);
  const [_summary, setSummary] = useState<DashboardSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [isAdmin, setIsAdmin] = useState(false);
  const [monitorData, setMonitorData] = useState<SupplierPriceMonitorData | null>(null);
  const [monitorLoading, setMonitorLoading] = useState(false);
  const [monitorRefreshing, setMonitorRefreshing] = useState(false);
  const [monitorError, setMonitorError] = useState<string | null>(null);
  const [monitorDownloading, setMonitorDownloading] = useState(false);

  const loadData = async () => {
    try {
      setError(null);
      const [riskRes, orderRes, alertRes, summaryRes] = await Promise.all([
        fetchRiskScores(),
        fetchRecentOrders(),
        fetchInventoryAlerts(),
        fetchDashboardSummary(),
      ]);
      setRisks(riskRes.scores);
      setOrders(orderRes.orders);
      setAlerts(alertRes.alerts);
      setSummary(summaryRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : '대시보드 데이터를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  const loadMonitor = async (showSpinner = true) => {
    try {
      if (showSpinner) {
        setMonitorLoading(true);
      } else {
        setMonitorRefreshing(true);
      }
      setMonitorError(null);
      const summary = await fetchMyeongiSupplierPriceMonitor();
      setMonitorData(summary);
    } catch (e) {
      setMonitorError(e instanceof Error ? e.message : '명이나물 공급가 비교를 불러오지 못했습니다.');
    } finally {
      setMonitorLoading(false);
      setMonitorRefreshing(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshDashboardData();
      await loadData();
      if (isAdmin) {
        await loadMonitor(false);
      }
    } catch {
      setError('대시보드 새로고침에 실패했습니다.');
    } finally {
      setRefreshing(false);
    }
  };

  const handleDownloadMonitorWorkbook = async () => {
    try {
      setMonitorDownloading(true);
      setMonitorError(null);
      const result = await downloadMyeongiSupplierPriceMonitorWorkbook();
      downloadBlob(result.blob, result.filename);
      if (result.stats) {
        setMonitorData(result.stats as unknown as SupplierPriceMonitorData);
      }
    } catch (e) {
      setMonitorError(e instanceof Error ? e.message : '비교 엑셀 다운로드에 실패했습니다.');
    } finally {
      setMonitorDownloading(false);
    }
  };

  useEffect(() => {
    loadData();
    const bootstrap = async () => {
      try {
        const me = await fetchMe();
        if (me.role === 'admin') {
          setIsAdmin(true);
          await loadMonitor();
        }
      } catch {
        setIsAdmin(false);
      }
    };
    bootstrap();
    const interval = setInterval(loadData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="space-y-8 animate-fade-in">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((index) => (
            <SkeletonCard key={index} />
          ))}
        </div>
      </div>
    );
  }

  if (error && _risks.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center space-y-4 text-slate-500">
        <AlertCircle size={48} className="text-slate-400" />
        <p className="text-lg font-bold">대시보드 데이터를 불러오지 못했습니다</p>
        <p className="text-sm text-slate-400">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            loadData();
          }}
          className="rounded-xl bg-blue-600 px-6 py-2 font-bold text-white"
        >
          다시 시도
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-slate-800">통합 운영 대시보드</h2>
        <div className="flex items-center gap-3">
          <span className="flex items-center text-xs text-slate-400">
            <Clock size={14} className="mr-1 animate-pulse text-blue-400" />
            실시간 운영 모니터링
          </span>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-2 text-slate-400 transition-all hover:text-blue-600 disabled:opacity-50"
          >
            {refreshing ? <Loader2 size={20} className="animate-spin" /> : <RefreshCw size={20} />}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
        {MARKET_SCORES.map((market) => (
          <StatusCard key={market.id} market={market} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="space-y-8 lg:col-span-2">
          {isAdmin && (
            <section className="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
              <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div>
                  <div className="mb-2 flex items-center gap-2">
                    <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-100 text-blue-600">
                      <BellRing size={18} />
                    </div>
                    <div>
                      <p className="text-xs font-bold uppercase tracking-[0.24em] text-blue-500">Supplier Alert</p>
                      <h3 className="text-xl font-black text-slate-900">공급가 단가변경 바로 알림</h3>
                    </div>
                  </div>
                  <p className="text-sm leading-6 text-slate-500">
                    전날 저장된 쥬얼리프룻 공급가와 오늘 관리자 사이트 공급가를 비교합니다.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    onClick={() => loadMonitor(false)}
                    disabled={monitorRefreshing || monitorLoading || monitorDownloading}
                    className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-sm font-bold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {monitorRefreshing ? <Loader2 size={16} className="mr-2 animate-spin" /> : <RefreshCw size={16} className="mr-2" />}
                    단가 다시 확인
                  </button>
                  <button
                    onClick={handleDownloadMonitorWorkbook}
                    disabled={monitorLoading || monitorDownloading}
                    className="inline-flex items-center rounded-xl bg-blue-600 px-4 py-2 text-sm font-bold text-white transition hover:bg-blue-500 disabled:opacity-50"
                  >
                    {monitorDownloading ? <Loader2 size={16} className="mr-2 animate-spin" /> : <Download size={16} className="mr-2" />}
                    비교 엑셀 저장
                  </button>
                </div>
              </div>

              {monitorLoading ? (
                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  {[1, 2, 3].map((index) => (
                    <SkeletonCard key={index} />
                  ))}
                </div>
              ) : monitorError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
                  {monitorError}
                </div>
              ) : monitorData ? (
                <div className="space-y-5">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                      <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">대상 상품</p>
                      <p className="mt-2 text-lg font-black text-slate-900">{monitorData.product_name}</p>
                      <p className="mt-1 text-xs text-slate-500">거래처 {monitorData.supplier_name}</p>
                    </div>
                    <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4">
                      <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">전일 대비 상승</p>
                      <p className="mt-2 text-3xl font-black text-blue-700">{monitorData.blue_count}</p>
                      <p className="mt-1 text-xs text-blue-600">공급가가 오른 옵션</p>
                    </div>
                    <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4">
                      <p className="text-xs font-bold uppercase tracking-[0.18em] text-rose-600">전일 대비 하락</p>
                      <p className="mt-2 text-3xl font-black text-rose-700">{monitorData.red_count}</p>
                      <p className="mt-1 text-xs text-rose-600">공급가가 내린 옵션</p>
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                      <p className="text-xs font-bold uppercase tracking-[0.18em] text-slate-500">마지막 갱신</p>
                      <p className="mt-2 text-base font-black text-slate-900">
                        {new Date(monitorData.checked_at).toLocaleString('ko-KR')}
                      </p>
                      <p className="mt-1 truncate text-xs text-slate-500">{monitorData.output_filename}</p>
                    </div>
                  </div>

                  <div className="space-y-3">
                    {monitorData.rows.map((row) => {
                      const style = signalStyle[row.signal];
                      const SignalIcon = style.icon;
                      return (
                        <div
                          key={row.option_name}
                          className={`rounded-2xl border p-4 ${style.row}`}
                        >
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
              ) : (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
                  아직 불러온 공급가 비교 결과가 없습니다.
                </div>
              )}
            </section>
          )}

          {isAdmin && <KolrabiSupplierPriceCard />}

          {isAdmin && <ChamoeAltteulSupplierPriceCard />}

          <section className="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
            <div className="mb-6 flex items-center justify-between">
              <h3 className="flex items-center text-lg font-bold">
                <ShoppingCart size={20} className="mr-2 text-blue-500" />
                업무가 필요한 주문 내역
              </h3>
              <button className="text-xs font-medium text-blue-500 hover:text-blue-700">전체보기</button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-sm text-slate-400">
                    <th className="pb-3 font-medium">마켓</th>
                    <th className="pb-3 font-medium">상품명</th>
                    <th className="pb-3 font-medium">상태</th>
                    <th className="pb-3 font-medium">시간</th>
                    <th className="pb-3 text-right font-medium">금액</th>
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {RECENT_ORDERS.map((order) => (
                    <tr key={order.id} className="border-b border-slate-50 transition-colors hover:bg-slate-50/50">
                      <td className="py-4">
                        <span className={`rounded px-2 py-1 text-[10px] font-bold ${marketBadgeClass(order.market)}`}>
                          {order.market}
                        </span>
                      </td>
                      <td className="py-4 font-medium text-slate-700">{order.product}</td>
                      <td className="py-4">
                        <span className={statusClass(order.status)}>{order.status}</span>
                      </td>
                      <td className="py-4 text-xs text-slate-400">{order.time}</td>
                      <td className="py-4 text-right font-bold text-slate-800">{order.price.toLocaleString()}원</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-800 to-slate-900 p-8 text-white shadow-xl">
            <div className="absolute right-0 top-0 h-64 w-64 translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500/10" />
            <div className="relative z-10">
              <div className="mb-4 flex items-center space-x-2">
                <Sparkles size={18} className="text-blue-400" />
                <span className="text-sm font-bold tracking-wide text-blue-300">AI 운영 가이드</span>
              </div>
              <h3 className="mb-3 text-xl font-black leading-tight">
                주문 흐름과 공급가 변동을 함께 보면서 빠르게 대응할 수 있게 준비했습니다.
              </h3>
              <p className="mb-6 max-w-lg text-sm leading-relaxed text-slate-300">
                최근 주문, 재고 경고, 공급가 변동을 한 화면에서 확인하고 필요한 파일까지 바로 내려받을 수 있습니다.
              </p>
              <button className="group flex items-center rounded-xl bg-blue-600 px-6 py-3 text-sm font-bold text-white transition-all hover:bg-blue-500">
                운영 도구 열기
                <ChevronRight size={16} className="ml-1 transition-transform group-hover:translate-x-1" />
              </button>
            </div>
          </section>
        </div>

        <div className="space-y-8">
          <section className="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
            <h3 className="mb-6 flex items-center text-lg font-bold">
              <Package size={20} className="mr-2 text-blue-500" />
              재고 최적화 제안
            </h3>
            <div className="space-y-4">
              {INVENTORY_ALERTS.map((item, index) => (
                <div key={`${item.name}-${index}`} className="rounded-2xl bg-slate-50 p-4">
                  <p className="text-sm font-bold text-slate-800">{item.name}</p>
                  <div className="mt-2 flex items-center justify-between">
                    <div>
                      <p className="text-xs text-slate-500">
                        안전 재고 한도{' '}
                        <span className={`font-bold ${item.status === 'critical' ? 'text-rose-600' : 'text-blue-600'}`}>
                          {item.stock}박스
                        </span>
                      </p>
                      <p className="mt-0.5 text-xs text-slate-400">추가 발주 여부를 확인해주세요.</p>
                    </div>
                    <button className="rounded-lg border border-blue-200 bg-white px-3 py-1.5 text-xs font-bold text-blue-600 transition-colors hover:bg-blue-50">
                      관리
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-3xl border border-slate-100 bg-white p-6 shadow-sm">
            <h3 className="mb-6 flex items-center text-lg font-bold">
              <MessageSquare size={20} className="mr-2 text-amber-500" />
              빠른 응답이 필요한 문의
            </h3>
            <div className="space-y-4">
              {CS_INQUIRIES.map((inquiry, index) => (
                <div key={`${inquiry.market}-${index}`} className="rounded-2xl bg-slate-50 p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <span className={`rounded px-2 py-0.5 text-[10px] font-bold ${marketBadgeClass(inquiry.market)}`}>
                      {inquiry.market}
                    </span>
                    <span className="text-[10px] text-slate-400">{inquiry.time}</span>
                  </div>
                  <p className="truncate text-sm font-bold text-slate-700">{inquiry.content}</p>
                  <div className="mt-2 flex items-center gap-2">
                    <span className="text-[10px] text-slate-400">#{inquiry.type}</span>
                    {inquiry.urgent && (
                      <span className="flex items-center text-[10px] font-bold text-rose-500">
                        <Shield size={10} className="mr-0.5" />
                        즉시 확인 필요
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default DashboardHome;
