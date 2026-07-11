"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import type { InboundParcel, InboundItem, ParcelStatus } from "@/lib/types";

const STAGES: { key: ParcelStatus; label: string; hl?: string }[] = [
  { key: "expected", label: "도착 예정" },
  { key: "arrived", label: "도착 처리됨" },
  { key: "inspecting", label: "검수 대기" },
  { key: "completed", label: "입고 완료" },
  { key: "issue", label: "이슈", hl: "text-red-500 border-red-300" },
];

const BADGE: Record<ParcelStatus, string> = {
  expected: "bg-slate-400",
  arrived: "bg-blue-500",
  inspecting: "bg-amber-500",
  completed: "bg-emerald-600",
  issue: "bg-red-500",
};

const LABEL: Record<ParcelStatus, string> = {
  expected: "도착예정",
  arrived: "도착",
  inspecting: "검수중",
  completed: "입고완료",
  issue: "이슈",
};

export default function InboundPage() {
  const supabase = useMemo(() => createClient(), []);
  const [parcels, setParcels] = useState<InboundParcel[]>([]);
  const [items, setItems] = useState<InboundItem[]>([]);
  const [filter, setFilter] = useState<ParcelStatus | "all">("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [{ data: ps }, { data: its }] = await Promise.all([
      supabase
        .from("inbound_parcels")
        .select("*")
        .order("created_at", { ascending: false }),
      supabase.from("inbound_items").select("*"),
    ]);
    setParcels((ps as InboundParcel[]) ?? []);
    setItems((its as InboundItem[]) ?? []);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    load();
  }, [load]);

  const count = (s: ParcelStatus) => parcels.filter((p) => p.status === s).length;
  const shown = filter === "all" ? parcels : parcels.filter((p) => p.status === filter);
  const itemsOf = (pid: string) => items.filter((i) => i.parcel_id === pid);

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold">입고 관리</h1>
          <p className="mt-1 text-xs text-slate-400">
            구매내역에서 운송장을 등록하면 여기 쌓입니다. 도착·검수는{" "}
            <Link href="/m/scan" className="text-blue-500 underline">
              📱 모바일 스캔
            </Link>
            에서.
          </p>
        </div>
        <button
          onClick={load}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
        >
          새로고침
        </button>
      </div>

      {/* 파이프라인 */}
      <div className="mt-4 flex flex-wrap gap-2">
        {STAGES.map((s) => (
          <button
            key={s.key}
            onClick={() => setFilter(filter === s.key ? "all" : s.key)}
            className={`min-w-24 flex-1 rounded-lg border p-3 text-center ${
              filter === s.key ? "border-blue-500 bg-blue-50" : "border-slate-200"
            } ${s.hl ?? ""}`}
          >
            <div className="text-xl font-bold">{count(s.key)}</div>
            <div className="text-[11px]">{s.label}</div>
          </button>
        ))}
      </div>

      <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="bg-slate-50 text-left text-slate-500">
              <th className="p-2">운송장번호</th>
              <th className="p-2">내용물</th>
              <th className="p-2">상태</th>
              <th className="p-2">처리 기록</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td className="p-3 text-slate-400" colSpan={4}>
                  불러오는 중…
                </td>
              </tr>
            )}
            {!loading && shown.length === 0 && (
              <tr>
                <td className="p-3 text-slate-400" colSpan={4}>
                  해당 상태의 박스가 없습니다.
                </td>
              </tr>
            )}
            {shown.map((p) => (
              <tr key={p.id} className="border-t border-slate-100 align-top">
                <td className="p-2 font-mono">{p.tracking_no}</td>
                <td className="p-2">
                  {itemsOf(p.id).map((i) => (
                    <div key={i.id}>
                      {i.raw_name}{" "}
                      <span className="text-slate-400">
                        {i.option_text} ×{i.expected_qty}
                      </span>
                      {i.condition && i.condition !== "ok" && (
                        <span className="ml-1 rounded bg-red-50 px-1 text-[10px] text-red-500">
                          {i.condition === "short"
                            ? "수량부족"
                            : i.condition === "wrong"
                              ? "오배송"
                              : "불량"}
                        </span>
                      )}
                    </div>
                  ))}
                </td>
                <td className="p-2">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] text-white ${BADGE[p.status]}`}
                  >
                    {LABEL[p.status]}
                  </span>
                </td>
                <td className="p-2 text-[11px] text-slate-400">
                  {p.arrived_by && (
                    <div>
                      도착 {p.arrived_by} ·{" "}
                      {p.arrived_at && new Date(p.arrived_at).toLocaleString("ko-KR")}
                    </div>
                  )}
                  {p.inspected_by && (
                    <div>
                      검수 {p.inspected_by} ·{" "}
                      {p.inspected_at &&
                        new Date(p.inspected_at).toLocaleString("ko-KR")}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
