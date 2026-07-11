"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { useWorkspace } from "./workspace-provider";

const NAV = [
  {
    group: "소싱",
    items: [{ href: "/sourcing", label: "시세·마진 계산" }],
  },
  {
    group: "장부",
    items: [
      { href: "/ledger/purchases", label: "구매내역" },
      { href: "/ledger/inbound", label: "입고 관리" },
    ],
  },
  {
    group: "설정",
    items: [{ href: "/settings", label: "계정 연동" }],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const ws = useWorkspace();

  async function logout() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-slate-200 bg-slate-50/60 p-3">
      <div className="mb-4 px-2">
        <div className="text-sm font-bold text-slate-800">□ 브랜드리셀OS</div>
        <div className="mt-0.5 truncate text-[11px] text-slate-400">
          {ws.workspaceName}
        </div>
      </div>

      <nav className="flex-1 space-y-4">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="mb-1 px-2 text-[10px] font-medium uppercase tracking-wide text-slate-400">
              {g.group}
            </div>
            {g.items.map((it) => {
              const active = pathname.startsWith(it.href);
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  className={`block rounded-md px-2.5 py-2 text-[13px] ${
                    active
                      ? "bg-blue-50 font-semibold text-blue-600"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  {it.label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <Link
        href="/m/scan"
        className="mb-2 rounded-md px-2.5 py-2 text-[13px] text-slate-600 hover:bg-slate-100"
      >
        📱 모바일 스캔
      </Link>
      <div className="border-t border-slate-200 pt-2">
        <div className="truncate px-2 text-[11px] text-slate-400">
          {ws.email}
        </div>
        <button
          onClick={logout}
          className="mt-1 w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-slate-500 hover:bg-slate-100"
        >
          로그아웃
        </button>
      </div>
    </aside>
  );
}
