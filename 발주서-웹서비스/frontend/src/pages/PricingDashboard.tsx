import { useState, useEffect } from 'react';
import {
  Shield,
  AlertTriangle,
  TrendingDown,
  Loader2,
  Plus,
  Trash2,
  History,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  fetchMargins,
  fetchPricingRules,
  fetchPricingProposals,
  fetchPricingLog,
  createPricingRule,
  deletePricingRule,
  fetchProducts,
  type MarginData,
  type PricingRuleData,
  type PriceProposalData,
  type PriceLogData,
  type ProductData,
  type PricingRuleInput,
} from '../api';

function PricingDashboard() {
  const [margins, setMargins] = useState<MarginData[]>([]);
  const [rules, setRules] = useState<PricingRuleData[]>([]);
  const [proposals, setProposals] = useState<PriceProposalData[]>([]);
  const [logs, setLogs] = useState<PriceLogData[]>([]);
  const [products, setProducts] = useState<ProductData[]>([]);
  const [loading, setLoading] = useState(true);
  const [showLog, setShowLog] = useState(false);
  const [showAddRule, setShowAddRule] = useState(false);
  const [newRule, setNewRule] = useState<PricingRuleInput>({
    product_id: 0,
    min_margin_pct: 3.0,
    min_price: 0,
    max_price: 0,
    ad_stop_threshold: 1.0,
  });

  const loadData = async () => {
    try {
      const [m, r, p, l, prod] = await Promise.all([
        fetchMargins(),
        fetchPricingRules(),
        fetchPricingProposals(),
        fetchPricingLog(),
        fetchProducts(),
      ]);
      setMargins(m.margins);
      setRules(r.rules);
      setProposals(p.proposals);
      setLogs(l.logs);
      setProducts(prod.products);
    } catch (e) {
      console.error('Failed to load pricing data', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, []);

  const handleAddRule = async () => {
    if (!newRule.product_id) return;
    const product = products.find(p => p.seller_product_id === newRule.product_id);
    await createPricingRule({
      ...newRule,
      product_name: product?.product_name || '',
    });
    setShowAddRule(false);
    setNewRule({ product_id: 0, min_margin_pct: 3.0, min_price: 0, max_price: 0, ad_stop_threshold: 1.0 });
    await loadData();
  };

  const handleDeleteRule = async (productId: number) => {
    if (!confirm('이 가격 룰을 삭제하시겠습니까?')) return;
    await deletePricingRule(productId);
    await loadData();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={32} className="animate-spin text-blue-500" />
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-slate-800 flex items-center">
          <Shield size={24} className="mr-2 text-blue-600" />
          마진 방어 모니터링
        </h2>
        <span className="text-xs text-slate-400">모니터링 + 알림 모드</span>
      </div>

      {/* Proposals / Alerts */}
      {proposals.length > 0 && (
        <section className="bg-amber-50 border-2 border-amber-200 p-6 rounded-2xl">
          <h3 className="font-bold text-amber-800 mb-4 flex items-center">
            <AlertTriangle size={18} className="mr-2" />
            마진 위험 알림 ({proposals.length}건)
          </h3>
          <div className="space-y-3">
            {proposals.map((p) => (
              <div key={p.product_id} className="bg-white p-4 rounded-xl border border-amber-100 flex items-center justify-between">
                <div className="min-w-0 flex-1">
                  <p className="font-bold text-slate-800 text-sm truncate">{p.product_name}</p>
                  <p className="text-xs text-slate-500 mt-1">{p.reason}</p>
                </div>
                <div className="flex items-center gap-4 ml-4">
                  <div className="text-right">
                    <p className="text-xs text-slate-400">현재가</p>
                    <p className="font-bold text-slate-700">{p.current_price.toLocaleString()}원</p>
                  </div>
                  {p.proposed_price !== p.current_price && (
                    <div className="text-right">
                      <p className="text-xs text-blue-500">제안가</p>
                      <p className="font-bold text-blue-700">{p.proposed_price.toLocaleString()}원</p>
                    </div>
                  )}
                  {p.ad_stop_recommended && (
                    <span className="px-2 py-1 bg-rose-100 text-rose-700 text-[10px] font-bold rounded">
                      광고중지 권장
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Margin Monitor */}
      <section className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
        <h3 className="font-bold text-lg mb-6 flex items-center">
          <TrendingDown size={20} className="mr-2 text-slate-600" />
          상품별 마진 현황
        </h3>
        {margins.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-50">
                  <th className="pb-3 font-medium">상품명</th>
                  <th className="pb-3 font-medium text-right">판매가</th>
                  <th className="pb-3 font-medium text-right">추정원가</th>
                  <th className="pb-3 font-medium text-right">마진</th>
                  <th className="pb-3 font-medium text-right">마진율</th>
                  <th className="pb-3 font-medium text-center">상태</th>
                </tr>
              </thead>
              <tbody>
                {margins.map((m) => (
                  <tr key={m.product_id} className="border-b border-slate-50 hover:bg-slate-50/50">
                    <td className="py-3 font-medium text-slate-700 max-w-[200px] truncate">{m.product_name}</td>
                    <td className="py-3 text-right">{m.sale_price.toLocaleString()}원</td>
                    <td className="py-3 text-right text-slate-400">{m.estimated_cost.toLocaleString()}원</td>
                    <td className="py-3 text-right font-bold">{m.margin.toLocaleString()}원</td>
                    <td className="py-3 text-right">
                      <span className={`font-bold ${
                        m.margin_pct < 3 ? 'text-rose-600' :
                        m.margin_pct < 10 ? 'text-amber-600' : 'text-emerald-600'
                      }`}>
                        {m.margin_pct}%
                      </span>
                    </td>
                    <td className="py-3 text-center">
                      {m.ad_stop_recommended ? (
                        <span className="px-2 py-0.5 bg-rose-100 text-rose-700 text-[10px] font-bold rounded">위험</span>
                      ) : m.has_rule ? (
                        <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-[10px] font-bold rounded">관리중</span>
                      ) : (
                        <span className="px-2 py-0.5 bg-slate-100 text-slate-500 text-[10px] font-bold rounded">미설정</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-center text-slate-400 py-8">상품 데이터 없음</p>
        )}
      </section>

      {/* Pricing Rules */}
      <section className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-bold text-lg flex items-center">
            <Shield size={20} className="mr-2 text-blue-500" />
            가격 방어 룰 ({rules.length}개)
          </h3>
          <button
            onClick={() => setShowAddRule(!showAddRule)}
            className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white text-sm font-bold rounded-xl hover:bg-blue-700"
          >
            <Plus size={16} /> 룰 추가
          </button>
        </div>

        {showAddRule && (
          <div className="bg-blue-50 p-4 rounded-2xl mb-4 space-y-3">
            <div>
              <label className="text-xs font-bold text-slate-600 block mb-1">상품 선택</label>
              <select
                value={newRule.product_id}
                onChange={(e) => setNewRule({ ...newRule, product_id: Number(e.target.value) })}
                className="w-full border rounded-lg px-3 py-2 text-sm"
              >
                <option value={0}>상품을 선택하세요</option>
                {products.map(p => (
                  <option key={p.seller_product_id} value={p.seller_product_id}>
                    {p.product_name} ({p.sale_price.toLocaleString()}원)
                  </option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <label className="text-xs font-bold text-slate-600 block mb-1">최소 마진율(%)</label>
                <input type="number" step="0.5" value={newRule.min_margin_pct}
                  onChange={(e) => setNewRule({ ...newRule, min_margin_pct: Number(e.target.value) })}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="text-xs font-bold text-slate-600 block mb-1">최저가</label>
                <input type="number" value={newRule.min_price}
                  onChange={(e) => setNewRule({ ...newRule, min_price: Number(e.target.value) })}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="text-xs font-bold text-slate-600 block mb-1">최고가</label>
                <input type="number" value={newRule.max_price}
                  onChange={(e) => setNewRule({ ...newRule, max_price: Number(e.target.value) })}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="text-xs font-bold text-slate-600 block mb-1">광고중지 마진(%)</label>
                <input type="number" step="0.5" value={newRule.ad_stop_threshold}
                  onChange={(e) => setNewRule({ ...newRule, ad_stop_threshold: Number(e.target.value) })}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={handleAddRule} disabled={!newRule.product_id}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-bold rounded-xl disabled:opacity-50">
                저장
              </button>
              <button onClick={() => setShowAddRule(false)}
                className="px-4 py-2 bg-slate-200 text-slate-600 text-sm font-bold rounded-xl">
                취소
              </button>
            </div>
          </div>
        )}

        {rules.length > 0 ? (
          <div className="space-y-2">
            {rules.map((rule) => (
              <div key={rule.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl">
                <div className="min-w-0 flex-1">
                  <p className="font-bold text-slate-800 text-sm truncate">{rule.product_name}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    최소마진 {rule.min_margin_pct}% | 광고중지 {rule.ad_stop_threshold}%
                    {rule.min_price > 0 && ` | 최저 ${rule.min_price.toLocaleString()}원`}
                    {rule.max_price > 0 && ` | 최고 ${rule.max_price.toLocaleString()}원`}
                  </p>
                </div>
                <button onClick={() => handleDeleteRule(rule.product_id)}
                  className="ml-2 p-2 text-slate-400 hover:text-rose-600">
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-center text-slate-400 py-4 text-sm">설정된 가격 룰 없음</p>
        )}
      </section>

      {/* Audit Log */}
      <section className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
        <button
          onClick={() => setShowLog(!showLog)}
          className="w-full flex items-center justify-between"
        >
          <h3 className="font-bold text-lg flex items-center">
            <History size={20} className="mr-2 text-slate-500" />
            변경 이력 ({logs.length}건)
          </h3>
          {showLog ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
        </button>

        {showLog && logs.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-400 border-b border-slate-50">
                  <th className="pb-3 font-medium">시간</th>
                  <th className="pb-3 font-medium">상품</th>
                  <th className="pb-3 font-medium text-right">변경 전</th>
                  <th className="pb-3 font-medium text-right">변경 후</th>
                  <th className="pb-3 font-medium">사유</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} className="border-b border-slate-50">
                    <td className="py-2 text-xs text-slate-400">{log.executed_at?.slice(0, 16).replace('T', ' ')}</td>
                    <td className="py-2 text-slate-700 truncate max-w-[150px]">{log.product_name}</td>
                    <td className="py-2 text-right">{log.old_price.toLocaleString()}원</td>
                    <td className="py-2 text-right font-bold">{log.new_price.toLocaleString()}원</td>
                    <td className="py-2 text-slate-500 text-xs">{log.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {showLog && logs.length === 0 && (
          <p className="mt-4 text-center text-slate-400 text-sm">변경 이력 없음</p>
        )}
      </section>
    </div>
  );
}

export default PricingDashboard;
