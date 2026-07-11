"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setErr("");
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${location.origin}/auth/callback` },
    });
    setLoading(false);
    if (error) setErr(error.message);
    else setSent(true);
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-center text-lg font-bold text-slate-800">
          브랜드리셀OS
        </h1>
        <p className="mt-1 text-center text-xs text-slate-400">
          소싱 · 장부 · 입고 관리
        </p>

        {sent ? (
          <div className="mt-6 rounded-lg bg-blue-50 p-4 text-center text-sm text-blue-700">
            <b>{email}</b> 로 로그인 링크를 보냈어요.
            <br />
            메일의 링크를 눌러 로그인하세요.
          </div>
        ) : (
          <form onSubmit={submit} className="mt-6 space-y-3">
            <label className="block text-xs font-medium text-slate-600">
              이메일
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
            {err && <p className="text-xs text-red-500">{err}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "전송 중…" : "로그인 링크 받기"}
            </button>
          </form>
        )}
        <p className="mt-4 text-center text-[11px] leading-relaxed text-slate-400">
          비밀번호 없이 이메일 링크로 로그인합니다.
        </p>
      </div>
    </main>
  );
}
