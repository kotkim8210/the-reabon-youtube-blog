"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { useWorkspace } from "@/components/workspace-provider";
import { calcScenarios, sellThroughMonths, type FeeRule } from "@/lib/margin";
import { won, pct, months } from "@/lib/format";
import type { Product, MarketSnapshot } from "@/lib/types";

export default function SourcingPage() {
  const ws = useWorkspace();
  const supabase = useMemo(() => createClient(), []);

  const [products, setProducts] = useState<Product[]>([]);
  const [snapshots, setSnapshots] = useState<Record<string, MarketSnapshot>>({});
  const [kreamFee, setKreamFee] = useState<FeeRule>({
    platform: "kream",
    base_fee: 2500,
    rate_pct: 6.0,
  });
  const [selected, setSelected] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [{ data: prods }, { data: fee }, { data: snaps }] = await Promise.all([
      supabase
        .from("products")
        .select("*")
        .order("created_at", { ascending: false }),
      supabase
        .from("fee_rules")
        .select("base_fee, rate_pct")
        .eq("platform", "kream")
        .limit(1)
        .maybeSingle(),
      supabase
        .from("market_snapshots")
        .select("*")
        .eq("platform", "kream")
        .eq("size", "ALL")
        .order("captured_at", { ascending: false }),
    ]);
    setProducts((prods as Product[]) ?? []);
    if (fee) setKreamFee({ platform: "kream", ...fee } as FeeRule);
    // 상품별 최신 스냅샷만 유지
    const map: Record<string, MarketSnapshot> = {};
    for (const s of (snaps as MarketSnapshot[]) ?? []) {
      if (!map[s.product_id]) map[s.product_id] = s;
    }
    setSnapshots(map);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1 className="text-lg font-bold">시세 · 마진 계산</h1>
      <p className="mt-1 text-xs text-slate-400">
        상품을 등록하고 크림 시세를 입력하면 마진율·소진 개월이 자동 계산됩니다.
      </p>

      <AddProduct workspaceId={ws.workspaceId} onAdded={load} />

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* 상품 목록 */}
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="bg-slate-50 text-left text-slate-500">
                <th className="p-2">상품 / 품번</th>
                <th className="p-2">크림가</th>
                <th className="p-2">매물</th>
                <th className="p-2">월판매</th>
                <th className="p-2">소진</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td className="p-3 text-slate-400" colSpan={5}>
                    불러오는 중…
                  </td>
                </tr>
              )}
              {!loading && products.length === 0 && (
                <tr>
                  <td className="p-3 text-slate-400" colSpan={5}>
                    등록된 상품이 없습니다. 위에서 추가하세요.
                  </td>
                </tr>
              )}
              {products.map((p) => {
                const s = snapshots[p.id];
                const st = sellThroughMonths(
                  s?.total_listings ?? null,
                  s?.monthly_sales ?? null,
                );
                const active = selected?.id === p.id;
                return (
                  <tr
                    key={p.id}
                    onClick={() => setSelected(p)}
                    className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${
                      active ? "bg-blue-50" : ""
                    }`}
                  >
                    <td className="p-2">
                      <div className="font-medium">
                        {p.brand} {p.name}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        {p.style_code}
                      </div>
                    </td>
                    <td className="p-2">{won(s?.lowest_ask)}</td>
                    <td className="p-2">{s?.total_listings ?? "-"}</td>
                    <td className="p-2">{s?.monthly_sales ?? "-"}</td>
                    <td className="p-2">{months(st)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* 상세 / 마진 계산 */}
        <div>
          {selected ? (
            <Detail
              key={selected.id}
              product={selected}
              snapshot={snapshots[selected.id]}
              kreamFee={kreamFee}
              onSaved={load}
            />
          ) : (
            <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-xs text-slate-400">
              상품을 클릭하면 시세 입력 + 마진 계산기가 열립니다.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AddProduct({
  workspaceId,
  onAdded,
}: {
  workspaceId: string;
  onAdded: () => void;
}) {
  const supabase = useMemo(() => createClient(), []);
  const [open, setOpen] = useState(false);
  const [brand, setBrand] = useState("");
  const [name, setName] = useState("");
  const [style, setStyle] = useState("");
  const [category, setCategory] = useState("신발");
  const [busy, setBusy] = useState(false);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await supabase.from("products").insert({
      workspace_id: workspaceId,
      brand,
      name,
      style_code: style,
      category,
    });
    setBusy(false);
    setBrand("");
    setName("");
    setStyle("");
    setOpen(false);
    onAdded();
  }

  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-4 rounded-md border border-blue-500 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50"
      >
        + 상품 추가
      </button>
    );

  return (
    <form
      onSubmit={add}
      className="mt-4 flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3"
    >
      <Field label="브랜드" value={brand} onChange={setBrand} required w="w-28" />
      <Field label="상품명" value={name} onChange={setName} required w="w-44" />
      <Field label="품번" value={style} onChange={setStyle} required w="w-32" />
      <div>
        <label className="block text-[11px] text-slate-500">카테고리</label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1.5 text-xs"
        >
          <option>신발</option>
          <option>의류</option>
          <option>기타</option>
        </select>
      </div>
      <button
        disabled={busy}
        className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
      >
        저장
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="rounded-md px-2 py-1.5 text-xs text-slate-500"
      >
        취소
      </button>
    </form>
  );
}

function Detail({
  product,
  snapshot,
  kreamFee,
  onSaved,
}: {
  product: Product;
  snapshot?: MarketSnapshot;
  kreamFee: FeeRule;
  onSaved: () => void;
}) {
  const supabase = useMemo(() => createClient(), []);
  const [lowestAsk, setLowestAsk] = useState(snapshot?.lowest_ask?.toString() ?? "");
  const [totalListings, setTotalListings] = useState(
    snapshot?.total_listings?.toString() ?? "",
  );
  const [monthlySales, setMonthlySales] = useState(
    snapshot?.monthly_sales?.toString() ?? "",
  );
  const [buyPrice, setBuyPrice] = useState("");
  const [isBusiness, setIsBusiness] = useState(false);
  const [busy, setBusy] = useState(false);

  async function saveSnapshot(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    await supabase.from("market_snapshots").insert({
      workspace_id: product.workspace_id,
      product_id: product.id,
      platform: "kream",
      size: "ALL",
      lowest_ask: lowestAsk ? Number(lowestAsk) : null,
      total_listings: totalListings ? Number(totalListings) : null,
      monthly_sales: monthlySales ? Number(monthlySales) : null,
      source: "manual",
    });
    setBusy(false);
    onSaved();
  }

  const sell = Number(lowestAsk) || 0;
  const buy = Number(buyPrice) || 0;
  const scenarios =
    buy > 0 && sell > 0
      ? calcScenarios({
          buyPrice: buy,
          kreamSellPrice: sell,
          kreamFee,
          isBusiness,
        })
      : [];
  const st = sellThroughMonths(
    totalListings ? Number(totalListings) : null,
    monthlySales ? Number(monthlySales) : null,
  );

  return (
    <div className="space-y-3 rounded-lg border border-slate-200 p-4">
      <div>
        <div className="text-sm font-semibold">
          {product.brand} {product.name}
        </div>
        <div className="text-[11px] text-slate-400">{product.style_code}</div>
      </div>

      {/* 시세 입력 */}
      <form onSubmit={saveSnapshot} className="space-y-2 rounded-md bg-slate-50 p-3">
        <div className="text-[11px] font-medium text-slate-500">크림 시세 입력</div>
        <div className="flex flex-wrap gap-2">
          <Field label="즉시판매가" value={lowestAsk} onChange={setLowestAsk} type="number" w="w-28" />
          <Field label="총매물" value={totalListings} onChange={setTotalListings} type="number" w="w-24" />
          <Field label="월판매" value={monthlySales} onChange={setMonthlySales} type="number" w="w-24" />
        </div>
        <button
          disabled={busy}
          className="rounded-md border border-slate-300 bg-white px-3 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50"
        >
          시세 저장
        </button>
        {st != null && (
          <div className="text-[11px] text-slate-500">
            예상 소진: <b>{months(st)}</b>{" "}
            {st <= 1.5 ? "🔥 빠름" : st >= 6 ? "⚠️ 느림" : ""}
          </div>
        )}
      </form>

      {/* 마진 계산기 */}
      <div className="space-y-2 rounded-md border border-slate-200 p-3">
        <div className="text-[11px] font-medium text-slate-500">마진 계산기</div>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="내 매입가" value={buyPrice} onChange={setBuyPrice} type="number" w="w-32" />
          <label className="flex items-center gap-1 pb-1.5 text-[11px] text-slate-600">
            <input
              type="checkbox"
              checked={isBusiness}
              onChange={(e) => setIsBusiness(e.target.checked)}
            />
            사업자(부가세)
          </label>
        </div>

        {scenarios.length > 0 ? (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="py-1">시나리오</th>
                <th className="py-1">정산가</th>
                <th className="py-1">마진</th>
                <th className="py-1">마진율</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr key={s.key} className="border-t border-slate-100">
                  <td className="py-1">{s.label}</td>
                  <td className="py-1">{won(s.settle)}</td>
                  <td className={`py-1 font-semibold ${s.margin < 0 ? "text-red-500" : "text-emerald-600"}`}>
                    {s.margin < 0 ? "" : "+"}
                    {won(s.margin)}
                  </td>
                  <td className={`py-1 font-semibold ${s.margin < 0 ? "text-red-500" : "text-emerald-600"}`}>
                    {pct(s.marginRate)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-[11px] text-slate-400">
            매입가와 즉시판매가를 입력하면 마진이 계산됩니다.
          </div>
        )}
        {scenarios.some((s) => s.margin < 0) && (
          <div className="rounded bg-red-50 px-2 py-1 text-[11px] text-red-600">
            ⚠️ 적자 구간입니다. 매입가를 낮추거나 시세 회복을 기다리세요.
          </div>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  required,
  w = "w-32",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  w?: string;
}) {
  return (
    <div>
      <label className="block text-[11px] text-slate-500">{label}</label>
      <input
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${w} rounded border border-slate-300 px-2 py-1.5 text-xs outline-none focus:border-blue-500`}
      />
    </div>
  );
}
