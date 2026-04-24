import { useEffect, useMemo, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, PieChart, Pie, Cell, Legend,
} from 'recharts';
import { Search, TrendingUp, ChevronDown, ChevronRight } from 'lucide-react';
import {
  getSalesSummary, getSalesPresets, SalesRow,
  getSettlementCards, SettlementCard,
} from '../api';

function todayStr(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'];

export default function SalesDashboard() {
  const [dateFrom, setDateFrom] = useState(todayStr(-30));
  const [dateTo, setDateTo] = useState(todayStr(0));
  const [groupBy, setGroupBy] = useState<'option' | 'product' | 'day'>('option');
  const [rows, setRows] = useState<SalesRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [presets, setPresets] = useState<{ label: string; from: string; to: string }[]>([]);
  const [planCode, setPlanCode] = useState<string>('');

  // Settlement cards (today)
  const [cardDate, setCardDate] = useState<string>(todayStr(0));
  const [cards, setCards] = useState<SettlementCard[]>([]);
  const [cardsTotal, setCardsTotal] = useState<{ qty: number; krw: number }>({ qty: 0, krw: 0 });
  const [cardsLoading, setCardsLoading] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    getSalesPresets().then((r) => setPresets(r.presets)).catch(() => {});
  }, []);

  async function loadCards(date: string) {
    setCardsLoading(true);
    try {
      const r = await getSettlementCards(date);
      setCards(r.cards);
      setCardsTotal({ qty: r.total_qty, krw: r.total_settlement_krw });
    } catch {
      setCards([]);
      setCardsTotal({ qty: 0, krw: 0 });
    } finally {
      setCardsLoading(false);
    }
  }

  useEffect(() => {
    loadCards(cardDate);
  }, [cardDate]);

  function toggleExpand(label: string) {
    setExpanded((prev) => ({ ...prev, [label]: !prev[label] }));
  }

  async function search() {
    setLoading(true);
    setErr(null);
    try {
      const res = await getSalesSummary(dateFrom, dateTo, groupBy);
      setRows(res.rows);
      setPlanCode(res.plan_code);
      if (res.from !== dateFrom) setDateFrom(res.from);
      if (res.to !== dateTo) setDateTo(res.to);
    } catch (e: any) {
      setErr(e?.message || '조회 실패');
    } finally {
      setLoading(false);
    }
  }

  // Auto-load on mount
  useEffect(() => {
    search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupBy]);

  function applyPreset(p: { from: string; to: string }) {
    setDateFrom(p.from);
    setDateTo(p.to);
    setTimeout(() => search(), 0);
  }

  const chartData = useMemo(() => {
    if (groupBy === 'option') {
      return rows.map((r) => ({
        name: `${r.product_label || ''} / ${r.vendor_option_name || r.coupang_option_keyword || ''}`,
        qty: r.total_qty,
      }));
    }
    if (groupBy === 'product') {
      return rows.map((r) => ({ name: r.product_label || '-', qty: r.total_qty }));
    }
    return rows.map((r) => ({ name: r.ymd || '-', qty: r.total_qty }));
  }, [rows, groupBy]);

  const pieData = useMemo(() => {
    if (groupBy !== 'product') return [];
    return rows.slice(0, 8).map((r, i) => ({
      name: r.product_label || '-',
      value: r.total_qty,
      color: COLORS[i % COLORS.length],
    }));
  }, [rows, groupBy]);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">판매 대시보드</h1>
          <p className="text-slate-500 text-sm mt-1">
            옵션별 · 제품별 · 일별 판매량 추이
            {planCode === 'free' && <span className="ml-2 text-amber-600">(무료 플랜: 최근 30일)</span>}
          </p>
        </div>
      </header>

      {/* Settlement cards (per product, daily) */}
      <section className="bg-white rounded-xl shadow-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <TrendingUp size={18} className="text-indigo-600" />
            <h2 className="text-lg font-semibold text-slate-900">제품별 당일 정산</h2>
            <span className="text-xs text-slate-400">(옵션 단가 × 판매 수량)</span>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={cardDate}
              onChange={(e) => setCardDate(e.target.value)}
              className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              onClick={() => setCardDate(todayStr(0))}
              className="px-3 py-1.5 text-sm bg-slate-100 hover:bg-slate-200 rounded-lg text-slate-700"
            >
              오늘
            </button>
          </div>
        </div>

        {cardsLoading ? (
          <div className="py-8 text-center text-slate-400 text-sm">불러오는 중…</div>
        ) : cards.length === 0 ? (
          <div className="py-8 text-center text-slate-400 text-sm">
            해당 일자에 발주서 기록이 없습니다.
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {cards.map((c) => {
                const isOpen = !!expanded[c.product_label];
                return (
                  <div key={c.product_label} className="border border-slate-200 rounded-xl overflow-hidden">
                    <button
                      onClick={() => toggleExpand(c.product_label)}
                      className="w-full flex items-center justify-between p-4 hover:bg-slate-50 text-left"
                    >
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-900 truncate">{c.product_label}</p>
                        <p className="text-xs text-slate-500 mt-0.5">{c.total_qty.toLocaleString()}건 판매</p>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <div className="text-right">
                          <p className="text-sm font-bold text-indigo-600">
                            ₩{c.total_settlement_krw.toLocaleString()}
                          </p>
                          <p className="text-[10px] text-slate-400">정산</p>
                        </div>
                        {isOpen ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                      </div>
                    </button>
                    {isOpen && (
                      <div className="border-t border-slate-100 bg-slate-50 px-4 py-2 space-y-1">
                        {c.options.map((o, idx) => (
                          <div key={idx} className="flex items-center justify-between text-xs">
                            <div className="min-w-0 flex-1">
                              <p className="font-medium text-slate-700 truncate">
                                {o.vendor_option_name || o.coupang_option_keyword}
                              </p>
                              {o.vendor_option_name && (
                                <p className="text-[10px] text-slate-400 truncate">{o.coupang_option_keyword}</p>
                              )}
                            </div>
                            <div className="flex items-center gap-3 shrink-0 ml-2">
                              <span className="text-slate-600 font-medium">{o.quantity.toLocaleString()}개</span>
                              <span className="text-slate-400">
                                × ₩{o.unit_price_krw.toLocaleString()}
                              </span>
                              <span className="w-20 text-right font-semibold text-indigo-600">
                                ₩{o.settlement_krw.toLocaleString()}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4">
              <span className="text-sm text-slate-500">
                총 {cardsTotal.qty.toLocaleString()}건
              </span>
              <span className="text-lg font-bold text-slate-900">
                합계 ₩{cardsTotal.krw.toLocaleString()}
              </span>
            </div>
            {cards.some((c) => c.options.some((o) => !o.unit_price_krw)) && (
              <p className="mt-2 text-xs text-amber-600">
                ⚠ 단가가 0원인 옵션이 있습니다. 상품 설정에서 단가를 입력하면 정산비용이 자동 계산됩니다.
              </p>
            )}
          </>
        )}
      </section>

      {/* Filters */}
      <section className="bg-white rounded-xl shadow-sm p-5 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">시작일</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">종료일</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <button
            onClick={search}
            disabled={loading}
            aria-label="조회"
            className="flex items-center gap-1 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium px-4 py-2 rounded-lg"
          >
            <Search size={16} />
            조회
          </button>

          <div className="ml-auto flex gap-1">
            {(['option', 'product', 'day'] as const).map((g) => (
              <button
                key={g}
                onClick={() => setGroupBy(g)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                  groupBy === g ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {g === 'option' ? '옵션별' : g === 'product' ? '제품별' : '일별'}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {presets.map((p) => (
            <button
              key={p.label}
              onClick={() => applyPreset(p)}
              className="px-3 py-1 text-sm bg-slate-100 hover:bg-slate-200 rounded-full text-slate-700"
            >
              {p.label}
            </button>
          ))}
        </div>
      </section>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-2 rounded-lg">{err}</div>}

      {/* Chart */}
      <section className="bg-white rounded-xl shadow-sm p-5">
        <h2 className="text-lg font-semibold text-slate-900 mb-3">
          {groupBy === 'day' ? '일별 총 판매량' : groupBy === 'product' ? '제품별 판매량' : '옵션별 판매량'}
        </h2>
        {chartData.length === 0 ? (
          <div className="py-16 text-center text-slate-400">데이터가 없습니다. 발주서를 생성하면 여기에 집계됩니다.</div>
        ) : (
          <div className="w-full" style={{ height: 360 }}>
            <ResponsiveContainer>
              {groupBy === 'day' ? (
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="qty" stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              ) : (
                <BarChart data={chartData} layout="vertical" margin={{ left: 120 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis dataKey="name" type="category" tick={{ fontSize: 11 }} width={200} />
                  <Tooltip />
                  <Bar dataKey="qty" fill="#6366f1" radius={[0, 4, 4, 0]} />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {groupBy === 'product' && pieData.length > 0 && (
        <section className="bg-white rounded-xl shadow-sm p-5">
          <h2 className="text-lg font-semibold text-slate-900 mb-3">제품 비중</h2>
          <div className="w-full" style={{ height: 300 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={100} label={(e: any) => e.name}>
                  {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <Legend />
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Table */}
      <section className="bg-white rounded-xl shadow-sm p-5">
        <h2 className="text-lg font-semibold text-slate-900 mb-3">상세 내역</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-xs uppercase text-slate-500 border-b border-slate-200">
              <tr>
                {groupBy === 'option' && <>
                  <th className="text-left py-2 pr-4">제품</th>
                  <th className="text-left py-2 pr-4">옵션 (쿠팡)</th>
                  <th className="text-left py-2 pr-4">공급사 품목명</th>
                </>}
                {groupBy === 'product' && <th className="text-left py-2 pr-4">제품</th>}
                {groupBy === 'day' && <th className="text-left py-2 pr-4">날짜</th>}
                <th className="text-right py-2">총 수량</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                  {groupBy === 'option' && <>
                    <td className="py-2 pr-4">{r.product_label}</td>
                    <td className="py-2 pr-4 text-slate-500">{r.coupang_option_keyword}</td>
                    <td className="py-2 pr-4">{r.vendor_option_name || '-'}</td>
                  </>}
                  {groupBy === 'product' && <td className="py-2 pr-4">{r.product_label}</td>}
                  {groupBy === 'day' && <td className="py-2 pr-4">{r.ymd}</td>}
                  <td className="py-2 text-right font-medium">{r.total_qty.toLocaleString()}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={4} className="py-8 text-center text-slate-400">데이터 없음</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
