"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useWorkspace } from "@/components/workspace-provider";
import { won } from "@/lib/format";
import type { Purchase } from "@/lib/types";

export default function PurchasesPage() {
  const ws = useWorkspace();
  const supabase = useMemo(() => createClient(), []);
  const [rows, setRows] = useState<Purchase[]>([]);
  const [loading, setLoading] = useState(true);
  const [showPaste, setShowPaste] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const { data } = await supabase
      .from("purchases")
      .select("*")
      .order("ordered_at", { ascending: false });
    setRows((data as Purchase[]) ?? []);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    load();
  }, [load]);

  async function togglePersonal(p: Purchase) {
    await supabase
      .from("purchases")
      .update({ is_personal: !p.is_personal })
      .eq("id", p.id);
    load();
  }

  return (
    <div>
      <h1 className="text-lg font-bold">구매내역</h1>
      <p className="mt-1 text-xs text-slate-400">
        구매를 기록하고, 입고 예정으로 보내 검수하세요. 개인용 구매는 체크해 장부에서 구분합니다.
      </p>

      <div className="mt-3 flex gap-2">
        <AddPurchase workspaceId={ws.workspaceId} onAdded={load} />
        <button
          onClick={() => setShowPaste((v) => !v)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
        >
          붙여넣기 가져오기
        </button>
      </div>

      {showPaste && (
        <PasteImport
          workspaceId={ws.workspaceId}
          onDone={() => {
            setShowPaste(false);
            load();
          }}
        />
      )}

      <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="bg-slate-50 text-left text-slate-500">
              <th className="p-2">주문일</th>
              <th className="p-2">상품</th>
              <th className="p-2">옵션·수량</th>
              <th className="p-2">결제</th>
              <th className="p-2">배송지</th>
              <th className="p-2">개인용</th>
              <th className="p-2">입고</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td className="p-3 text-slate-400" colSpan={7}>
                  불러오는 중…
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td className="p-3 text-slate-400" colSpan={7}>
                  구매내역이 없습니다.
                </td>
              </tr>
            )}
            {rows.map((p) => (
              <PurchaseRow
                key={p.id}
                p={p}
                onTogglePersonal={() => togglePersonal(p)}
                onInbound={load}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PurchaseRow({
  p,
  onTogglePersonal,
  onInbound,
}: {
  p: Purchase;
  onTogglePersonal: () => void;
  onInbound: () => void;
}) {
  const supabase = useMemo(() => createClient(), []);
  const [open, setOpen] = useState(false);
  const [tracking, setTracking] = useState("");
  const [busy, setBusy] = useState(false);

  async function register(e: React.FormEvent) {
    e.preventDefault();
    if (!tracking.trim()) return;
    setBusy(true);
    const { data: parcel } = await supabase
      .from("inbound_parcels")
      .insert({
        workspace_id: p.workspace_id,
        tracking_no: tracking.trim(),
        status: "expected",
      })
      .select()
      .single();
    if (parcel) {
      await supabase.from("inbound_items").insert({
        workspace_id: p.workspace_id,
        parcel_id: parcel.id,
        purchase_id: p.id,
        raw_name: p.raw_name,
        option_text: p.option_text,
        expected_qty: p.qty,
      });
      await supabase
        .from("purchases")
        .update({ status: "shipping" })
        .eq("id", p.id);
    }
    setBusy(false);
    setOpen(false);
    setTracking("");
    onInbound();
  }

  return (
    <tr className="border-t border-slate-100">
      <td className="p-2">{p.ordered_at}</td>
      <td className="p-2">{p.raw_name}</td>
      <td className="p-2">
        {p.option_text} × {p.qty}
      </td>
      <td className="p-2">{won(p.paid_total)}</td>
      <td className="p-2">{p.ship_to ?? "-"}</td>
      <td className="p-2">
        <input
          type="checkbox"
          checked={p.is_personal}
          onChange={onTogglePersonal}
        />
      </td>
      <td className="p-2">
        {open ? (
          <form onSubmit={register} className="flex gap-1">
            <input
              autoFocus
              value={tracking}
              onChange={(e) => setTracking(e.target.value)}
              placeholder="운송장번호"
              className="w-32 rounded border border-slate-300 px-2 py-1 text-[11px]"
            />
            <button
              disabled={busy}
              className="rounded bg-blue-600 px-2 py-1 text-[11px] text-white"
            >
              등록
            </button>
          </form>
        ) : (
          <button
            onClick={() => setOpen(true)}
            className="rounded border border-blue-500 px-2 py-1 text-[11px] text-blue-600 hover:bg-blue-50"
          >
            입고 예정 등록
          </button>
        )}
      </td>
    </tr>
  );
}

function AddPurchase({
  workspaceId,
  onAdded,
}: {
  workspaceId: string;
  onAdded: () => void;
}) {
  const supabase = useMemo(() => createClient(), []);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({
    raw_name: "",
    option_text: "",
    qty: "1",
    paid_total: "",
    ship_to: "",
  });
  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v }));

  async function add(e: React.FormEvent) {
    e.preventDefault();
    await supabase.from("purchases").insert({
      workspace_id: workspaceId,
      raw_name: f.raw_name,
      option_text: f.option_text || null,
      qty: Number(f.qty) || 1,
      paid_total: Number(f.paid_total) || 0,
      ship_to: f.ship_to || null,
      source: "manual",
    });
    setF({ raw_name: "", option_text: "", qty: "1", paid_total: "", ship_to: "" });
    setOpen(false);
    onAdded();
  }

  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-md border border-blue-500 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50"
      >
        + 구매 추가
      </button>
    );

  return (
    <form
      onSubmit={add}
      className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3"
    >
      <I label="상품명" v={f.raw_name} on={(v) => set("raw_name", v)} req w="w-40" />
      <I label="옵션" v={f.option_text} on={(v) => set("option_text", v)} w="w-20" />
      <I label="수량" v={f.qty} on={(v) => set("qty", v)} t="number" w="w-16" />
      <I label="결제금액" v={f.paid_total} on={(v) => set("paid_total", v)} t="number" w="w-24" />
      <I label="배송지" v={f.ship_to} on={(v) => set("ship_to", v)} w="w-24" />
      <button className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white">
        저장
      </button>
      <button type="button" onClick={() => setOpen(false)} className="text-xs text-slate-500">
        취소
      </button>
    </form>
  );
}

function PasteImport({
  workspaceId,
  onDone,
}: {
  workspaceId: string;
  onDone: () => void;
}) {
  const supabase = useMemo(() => createClient(), []);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    // 각 줄: 상품명[\t 또는 ,]옵션[,]수량[,]결제금액
    const rows = text
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        const c = l.split(/\t|,/).map((x) => x.trim());
        return {
          workspace_id: workspaceId,
          raw_name: c[0] ?? l,
          option_text: c[1] || null,
          qty: Number(c[2]) || 1,
          paid_total: Number((c[3] ?? "").replace(/[^\d]/g, "")) || 0,
          source: "paste",
        };
      });
    if (rows.length) await supabase.from("purchases").insert(rows);
    setBusy(false);
    onDone();
  }

  return (
    <div className="mt-3 rounded-lg border border-slate-200 p-3">
      <div className="text-[11px] text-slate-500">
        한 줄에 한 건. 구분자: 탭 또는 쉼표 — 상품명, 옵션, 수량, 결제금액
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        className="mt-2 w-full rounded border border-slate-300 p-2 font-mono text-[11px]"
        placeholder={"아디다스 삼바\tL\t2\t74600\n폴로 셔츠\tM\t1\t89000"}
      />
      <button
        onClick={run}
        disabled={busy}
        className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
      >
        {busy ? "가져오는 중…" : "가져오기"}
      </button>
    </div>
  );
}

function I({
  label,
  v,
  on,
  t = "text",
  req,
  w = "w-32",
}: {
  label: string;
  v: string;
  on: (v: string) => void;
  t?: string;
  req?: boolean;
  w?: string;
}) {
  return (
    <div>
      <label className="block text-[11px] text-slate-500">{label}</label>
      <input
        type={t}
        required={req}
        value={v}
        onChange={(e) => on(e.target.value)}
        className={`${w} rounded border border-slate-300 px-2 py-1.5 text-xs`}
      />
    </div>
  );
}
