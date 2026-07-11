"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useWorkspace } from "@/components/workspace-provider";
import type { LinkedAccount } from "@/lib/types";

const PLATFORMS = [
  "musinsa",
  "29cm",
  "lotteon",
  "ssf",
  "kream",
  "kream_biz",
  "poizon",
  "soldout",
];

export default function SettingsPage() {
  const ws = useWorkspace();
  const supabase = useMemo(() => createClient(), []);
  const [accounts, setAccounts] = useState<LinkedAccount[]>([]);
  const [f, setF] = useState({
    platform: "musinsa",
    label: "",
    account_type: "buy",
    grade: "",
    mileage: "",
    next_grade_gap: "",
  });

  const load = useCallback(async () => {
    const { data } = await supabase
      .from("linked_accounts")
      .select("*")
      .order("platform");
    setAccounts((data as LinkedAccount[]) ?? []);
  }, [supabase]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    await supabase.from("linked_accounts").insert({
      workspace_id: ws.workspaceId,
      platform: f.platform,
      label: f.label,
      account_type: f.account_type,
      grade: f.grade || null,
      mileage: f.mileage ? Number(f.mileage) : null,
      next_grade_gap: f.next_grade_gap ? Number(f.next_grade_gap) : null,
    });
    setF({ ...f, label: "", grade: "", mileage: "", next_grade_gap: "" });
    load();
  }

  async function remove(id: string) {
    await supabase.from("linked_accounts").delete().eq("id", id);
    load();
  }

  return (
    <div>
      <h1 className="text-lg font-bold">계정 연동</h1>
      <p className="mt-1 text-xs text-slate-400">
        구매처·판매처 계정을 등록해 두고 등급/마일리지를 기록하세요 (Phase 1은 수동 기록).
        비밀번호는 저장하지 않습니다.
      </p>

      <form
        onSubmit={add}
        className="mt-4 flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3"
      >
        <div>
          <label className="block text-[11px] text-slate-500">플랫폼</label>
          <select
            value={f.platform}
            onChange={(e) => setF({ ...f, platform: e.target.value })}
            className="rounded border border-slate-300 px-2 py-1.5 text-xs"
          >
            {PLATFORMS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-[11px] text-slate-500">별칭</label>
          <input
            required
            value={f.label}
            onChange={(e) => setF({ ...f, label: e.target.value })}
            placeholder="musinsa_a01"
            className="w-32 rounded border border-slate-300 px-2 py-1.5 text-xs"
          />
        </div>
        <div>
          <label className="block text-[11px] text-slate-500">용도</label>
          <select
            value={f.account_type}
            onChange={(e) => setF({ ...f, account_type: e.target.value })}
            className="rounded border border-slate-300 px-2 py-1.5 text-xs"
          >
            <option value="buy">구매처</option>
            <option value="sell">판매처</option>
          </select>
        </div>
        <div>
          <label className="block text-[11px] text-slate-500">등급</label>
          <input
            value={f.grade}
            onChange={(e) => setF({ ...f, grade: e.target.value })}
            placeholder="플래티넘"
            className="w-24 rounded border border-slate-300 px-2 py-1.5 text-xs"
          />
        </div>
        <div>
          <label className="block text-[11px] text-slate-500">마일리지</label>
          <input
            type="number"
            value={f.mileage}
            onChange={(e) => setF({ ...f, mileage: e.target.value })}
            className="w-24 rounded border border-slate-300 px-2 py-1.5 text-xs"
          />
        </div>
        <div>
          <label className="block text-[11px] text-slate-500">다음등급까지</label>
          <input
            type="number"
            value={f.next_grade_gap}
            onChange={(e) => setF({ ...f, next_grade_gap: e.target.value })}
            className="w-24 rounded border border-slate-300 px-2 py-1.5 text-xs"
          />
        </div>
        <button className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white">
          추가
        </button>
      </form>

      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {accounts.map((a) => (
          <div key={a.id} className="rounded-lg border border-slate-200 p-3">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-sm font-semibold">{a.label}</div>
                <div className="text-[11px] text-slate-400">
                  {a.platform} · {a.account_type === "buy" ? "구매처" : "판매처"}
                </div>
              </div>
              <button
                onClick={() => remove(a.id)}
                className="text-[11px] text-slate-400 hover:text-red-500"
              >
                삭제
              </button>
            </div>
            <div className="mt-2 text-[11px] text-slate-500">
              {a.grade && <span className="mr-2">등급 {a.grade}</span>}
              {a.mileage != null && (
                <span className="mr-2">마일리지 {a.mileage.toLocaleString()}</span>
              )}
              {a.next_grade_gap != null && (
                <span>다음 등급까지 {a.next_grade_gap.toLocaleString()}원</span>
              )}
            </div>
          </div>
        ))}
        {accounts.length === 0 && (
          <div className="text-xs text-slate-400">등록된 계정이 없습니다.</div>
        )}
      </div>
    </div>
  );
}
