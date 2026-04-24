import { useState, useEffect } from 'react';
import {
  ShoppingCart,
  Package,
  Loader2,
  RefreshCw,
  AlertCircle,
  Clock,
  Sparkles,
  MessageSquare,
  ChevronRight,
  Shield,
} from 'lucide-react';
import {
  fetchRiskScores,
  fetchRecentOrders,
  fetchInventoryAlerts,
  fetchDashboardSummary,
  refreshDashboardData,
  type RiskScoreData,
  type OrderData,
  type InventoryAlertData,
  type DashboardSummaryData,
} from '../../api';
import StatusCard from './StatusCard';
import { MARKET_SCORES, RECENT_ORDERS, INVENTORY_ALERTS, CS_INQUIRIES } from './mockData';

function SkeletonCard() {
  return (
    <div className="p-5 rounded-2xl border-2 border-slate-200 bg-slate-50 animate-pulse">
      <div className="h-4 bg-slate-200 rounded w-3/4 mb-4" />
      <div className="h-8 bg-slate-200 rounded w-1/2 mb-4" />
      <div className="h-3 bg-slate-200 rounded w-full mb-2" />
      <div className="h-3 bg-slate-200 rounded w-2/3" />
    </div>
  );
}

const marketBadge: Record<string, string> = {
  '쿠팡': 'bg-blue-600 text-white',
  '네이버': 'bg-emerald-600 text-white',
  '지마켓': 'bg-red-500 text-white',
  '토스': 'bg-slate-800 text-white',
};

const statusStyle: Record<string, string> = {
  '신규주문': 'text-blue-600 font-bold',
  '배송준비': 'text-slate-600',
  '배송지연': 'text-red-500 font-bold',
  '확인필요': 'text-red-500 font-bold',
};

function DashboardHome() {
  // === 실제 쿠팡 API 데이터 (홀드 — 로드는 하지만 이 UI에서는 미사용) ===
  const [_risks, setRisks] = useState<RiskScoreData[]>([]);
  const [_orders, setOrders] = useState<OrderData[]>([]);
  const [_alerts, setAlerts] = useState<InventoryAlertData[]>([]);
  const [_summary, setSummary] = useState<DashboardSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      setError(e instanceof Error ? e.message : '데이터 로딩 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refreshDashboardData();
      await loadData();
    } catch (e) {
      setError('새로고침 실패');
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="space-y-8 animate-fade-in">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map(i => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (error && _risks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-slate-500 space-y-4">
        <AlertCircle size={48} className="text-slate-400" />
        <p className="text-lg font-bold">데이터를 불러올 수 없습니다</p>
        <p className="text-sm text-slate-400">{error}</p>
        <button
          onClick={() => { setLoading(true); loadData(); }}
          className="px-6 py-2 bg-blue-600 text-white rounded-xl font-bold"
        >
          다시 시도
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      {/* ========== 통합 판매자 점수 ========== */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-slate-800">
          통합 판매자 점수 (스마트 모니터링)
        </h2>
        <div className="flex items-center gap-3">
          <span className="flex items-center text-xs text-slate-400">
            <Clock size={14} className="mr-1 animate-pulse text-blue-400" />
            실시간 데이터 분석 중
          </span>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-2 text-slate-400 hover:text-blue-600 transition-all disabled:opacity-50"
          >
            {refreshing ? <Loader2 size={20} className="animate-spin" /> : <RefreshCw size={20} />}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {MARKET_SCORES.map(market => (
          <StatusCard key={market.id} market={market} />
        ))}
      </div>

      {/* ========== 중간 영역: 주문 + 재고 ========== */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* 업무가 필요한 주문 내역 */}
        <div className="lg:col-span-2 space-y-8">
          <section className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
            <div className="flex items-center justify-between mb-6">
              <h3 className="font-bold text-lg flex items-center">
                <ShoppingCart size={20} className="mr-2 text-blue-500" />
                업무가 필요한 주문 내역
              </h3>
              <button className="text-xs text-blue-500 hover:text-blue-700 font-medium">전체보기</button>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-slate-400 text-sm border-b border-slate-100">
                    <th className="pb-3 font-medium">마켓</th>
                    <th className="pb-3 font-medium">상품명</th>
                    <th className="pb-3 font-medium">상태</th>
                    <th className="pb-3 font-medium">시간</th>
                    <th className="pb-3 font-medium text-right">금액</th>
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {RECENT_ORDERS.map((order) => (
                    <tr key={order.id} className="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
                      <td className="py-4">
                        <span className={`px-2 py-1 rounded text-[10px] font-bold ${marketBadge[order.market] || 'bg-slate-200 text-slate-700'}`}>
                          {order.market}
                        </span>
                      </td>
                      <td className="py-4 font-medium text-slate-700">{order.product}</td>
                      <td className="py-4">
                        <span className={statusStyle[order.status] || 'text-slate-500'}>
                          {order.status}
                        </span>
                      </td>
                      <td className="py-4 text-slate-400 text-xs">{order.time}</td>
                      <td className="py-4 text-right font-bold text-slate-800">{order.price.toLocaleString()}원</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* AI 채널 보호 가이드 */}
          <section className="bg-gradient-to-br from-slate-800 to-slate-900 p-8 rounded-3xl shadow-xl text-white relative overflow-hidden">
            <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/10 rounded-full -translate-y-1/2 translate-x-1/2" />
            <div className="relative z-10">
              <div className="flex items-center space-x-2 mb-4">
                <Sparkles size={18} className="text-blue-400" />
                <span className="text-sm font-bold tracking-wide text-blue-300">AI 채널 보호 가이드</span>
              </div>
              <h3 className="text-xl font-black mb-3 leading-tight">
                지마켓 판매 점수를 <span className="underline decoration-blue-400 decoration-2 underline-offset-4">안전하게 보호</span>할 준비가 되었습니다.
              </h3>
              <p className="text-sm text-slate-300 mb-6 leading-relaxed max-w-lg">
                현재 지마켓에서 배송 지연 및 미응답 문의가 다소 증가하고 있습니다.
                AI가 분석한 원인에 따라 <b>지연 공지 자동 발송</b> 및 <b>우선 처리 리포트</b>를 실행하여
                패널티를 사전에 방지하세요.
              </p>
              <button className="px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-bold text-sm transition-all flex items-center group">
                AI 점수 복구 시작
                <ChevronRight size={16} className="ml-1 group-hover:translate-x-1 transition-transform" />
              </button>
            </div>
          </section>
        </div>

        {/* 오른쪽 사이드 */}
        <div className="space-y-8">
          {/* 재고 최적화 제안 */}
          <section className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
            <h3 className="font-bold text-lg mb-6 flex items-center">
              <Package size={20} className="mr-2 text-blue-500" />
              재고 최적화 제안
            </h3>
            <div className="space-y-4">
              {INVENTORY_ALERTS.map((item, idx) => (
                <div key={idx} className="p-4 bg-slate-50 rounded-2xl">
                  <p className="font-bold text-slate-800 text-sm">{item.name}</p>
                  <div className="flex items-center justify-between mt-2">
                    <div>
                      <p className="text-xs text-slate-500">
                        안전 재고 하한선{' '}
                        <span className={`font-bold ${item.status === 'critical' ? 'text-rose-600' : 'text-blue-600'}`}>
                          {item.stock}박스
                        </span>
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">도달:</p>
                    </div>
                    <button className="px-3 py-1.5 bg-white border border-blue-200 text-blue-600 rounded-lg text-xs font-bold hover:bg-blue-50 transition-colors">
                      관리
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* 빠른 응대가 필요한 문의 */}
          <section className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
            <h3 className="font-bold text-lg mb-6 flex items-center">
              <MessageSquare size={20} className="mr-2 text-amber-500" />
              빠른 응대가 필요한 문의
            </h3>
            <div className="space-y-4">
              {CS_INQUIRIES.map((inq, idx) => (
                <div key={idx} className="p-4 bg-slate-50 rounded-2xl">
                  <div className="flex items-center justify-between mb-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${marketBadge[inq.market] || 'bg-slate-200 text-slate-700'}`}>
                      {inq.market}
                    </span>
                    <span className="text-[10px] text-slate-400">{inq.time}</span>
                  </div>
                  <p className="text-sm font-bold text-slate-700 truncate">{inq.content}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="text-[10px] text-slate-400">#{inq.type}</span>
                    {inq.urgent && (
                      <span className="text-[10px] font-bold text-rose-500 flex items-center">
                        <Shield size={10} className="mr-0.5" />
                        점수 보호 필요
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
