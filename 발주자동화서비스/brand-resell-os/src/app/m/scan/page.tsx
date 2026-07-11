"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { useWorkspace } from "@/components/workspace-provider";
import { decodeFrame, digitsOnly } from "@/lib/scan";
import type { InboundParcel, InboundItem } from "@/lib/types";

type Mode = "arrive" | "inspect";

export default function ScanPage() {
  const ws = useWorkspace();
  const supabase = useMemo(() => createClient(), []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [mode, setMode] = useState<Mode>("arrive");
  const [camOn, setCamOn] = useState(false);
  const [camErr, setCamErr] = useState("");
  const [manual, setManual] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [parcel, setParcel] = useState<InboundParcel | null>(null);
  const [items, setItems] = useState<InboundItem[]>([]);
  const busyRef = useRef(false);
  const lastRef = useRef<string>("");

  const push = (m: string) => setLog((l) => [m, ...l].slice(0, 8));

  // 카메라 시작/정지
  useEffect(() => {
    if (!camOn) return;
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
        });
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        timer = setInterval(tick, 500);
      } catch {
        setCamErr("카메라를 열 수 없습니다. 수동 입력을 사용하세요.");
        setCamOn(false);
      }
    })();
    return () => {
      if (timer) clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camOn]);

  async function tick() {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c || v.readyState < 2 || busyRef.current) return;
    busyRef.current = true;
    try {
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(v, 0, 0, c.width, c.height);
      const img = ctx.getImageData(0, 0, c.width, c.height);
      const code = await decodeFrame(img);
      if (code && code !== lastRef.current) {
        lastRef.current = code;
        await handleCode(code);
      }
    } finally {
      busyRef.current = false;
    }
  }

  async function handleCode(raw: string) {
    const code = raw.trim();
    if (navigator.vibrate) navigator.vibrate(80);
    // 운송장 매칭: 정확일치 우선, 없으면 숫자만 비교
    const { data: rows } = await supabase
      .from("inbound_parcels")
      .select("*")
      .order("created_at", { ascending: false });
    const list = (rows as InboundParcel[]) ?? [];
    const d = digitsOnly(code);
    const found =
      list.find((p) => p.tracking_no === code) ??
      list.find((p) => digitsOnly(p.tracking_no) === d);

    if (!found) {
      push(`❓ ${code} — 예정 목록에 없음`);
      return;
    }

    if (mode === "arrive") {
      await supabase
        .from("inbound_parcels")
        .update({
          status: "arrived",
          arrived_by: ws.email,
          arrived_at: new Date().toISOString(),
        })
        .eq("id", found.id);
      push(`✅ ${found.tracking_no} — 도착 처리 완료`);
    } else {
      const { data: its } = await supabase
        .from("inbound_items")
        .select("*")
        .eq("parcel_id", found.id);
      setParcel(found);
      setItems((its as InboundItem[]) ?? []);
      push(`🔍 ${found.tracking_no} — 검수 시작`);
    }
  }

  async function setCondition(itemId: string, cond: InboundItem["condition"]) {
    await supabase
      .from("inbound_items")
      .update({ condition: cond })
      .eq("id", itemId);
    setItems((its) =>
      its.map((i) => (i.id === itemId ? { ...i, condition: cond } : i)),
    );
  }

  async function completeInspect() {
    if (!parcel) return;
    const hasIssue = items.some(
      (i) => i.condition && i.condition !== "ok",
    );
    await supabase
      .from("inbound_parcels")
      .update({
        status: hasIssue ? "issue" : "completed",
        inspected_by: ws.email,
        inspected_at: new Date().toISOString(),
      })
      .eq("id", parcel.id);
    push(
      `${hasIssue ? "⚠️ 이슈로" : "✅ 입고완료로"} 처리: ${parcel.tracking_no}`,
    );
    setParcel(null);
    setItems([]);
    lastRef.current = "";
  }

  return (
    <div className="p-4">
      <h1 className="text-base font-bold">📦 송장 스캔</h1>
      <div className="mt-1 text-[11px] text-slate-400">{ws.email}</div>

      {/* 모드 */}
      <div className="mt-3 flex gap-1 text-xs">
        {(["arrive", "inspect"] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => {
              setMode(m);
              setParcel(null);
              lastRef.current = "";
            }}
            className={`flex-1 rounded-md border py-2 ${
              mode === m
                ? "border-slate-800 bg-slate-800 text-white"
                : "border-slate-300 text-slate-600"
            }`}
          >
            {m === "arrive" ? "① 도착 처리" : "② 검수"}
          </button>
        ))}
      </div>

      {/* 카메라 */}
      <div className="mt-3 overflow-hidden rounded-lg border border-slate-200 bg-black">
        <video
          ref={videoRef}
          playsInline
          muted
          className={`h-52 w-full object-cover ${camOn ? "" : "hidden"}`}
        />
        {!camOn && (
          <div className="flex h-52 items-center justify-center">
            <button
              onClick={() => {
                setCamErr("");
                setCamOn(true);
              }}
              className="rounded-lg bg-white/90 px-4 py-2 text-sm font-semibold"
            >
              📷 카메라로 스캔 시작
            </button>
          </div>
        )}
      </div>
      <canvas ref={canvasRef} className="hidden" />
      {camErr && <p className="mt-1 text-[11px] text-red-500">{camErr}</p>}
      {camOn && (
        <button
          onClick={() => setCamOn(false)}
          className="mt-1 text-[11px] text-slate-400 underline"
        >
          카메라 끄기
        </button>
      )}

      {/* 수동 입력 */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (manual.trim()) {
            lastRef.current = "";
            handleCode(manual.trim());
            setManual("");
          }
        }}
        className="mt-3 flex gap-2"
      >
        <input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="운송장번호 직접 입력"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
          inputMode="numeric"
        />
        <button className="rounded-md bg-blue-600 px-3 text-sm font-semibold text-white">
          조회
        </button>
      </form>

      {/* 검수 패널 */}
      {mode === "inspect" && parcel && (
        <div className="mt-4 rounded-lg border border-slate-200 p-3">
          <div className="text-xs font-semibold">{parcel.tracking_no}</div>
          {items.length === 0 && (
            <div className="mt-1 text-[11px] text-slate-400">
              연결된 품목이 없습니다.
            </div>
          )}
          {items.map((it) => (
            <div key={it.id} className="mt-2 rounded border border-slate-100 p-2">
              <div className="text-xs">
                {it.raw_name}{" "}
                <span className="text-slate-400">
                  {it.option_text} · {it.expected_qty}개
                </span>
              </div>
              <div className="mt-1 flex gap-1 text-[11px]">
                {(
                  [
                    ["ok", "정상", "bg-emerald-600"],
                    ["short", "수량부족", "bg-amber-500"],
                    ["wrong", "오배송", "bg-red-500"],
                    ["defect", "불량", "bg-slate-500"],
                  ] as const
                ).map(([c, label, color]) => (
                  <button
                    key={c}
                    onClick={() => setCondition(it.id, c)}
                    className={`flex-1 rounded py-1.5 text-white ${
                      it.condition === c ? color : "bg-slate-200 text-slate-500"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <button
            onClick={completeInspect}
            className="mt-3 w-full rounded-md bg-blue-600 py-2.5 text-sm font-semibold text-white"
          >
            저장 → 입고 완료
          </button>
        </div>
      )}

      {/* 로그 */}
      <div className="mt-4 space-y-1">
        {log.map((l, i) => (
          <div
            key={i}
            className="rounded bg-slate-50 px-3 py-2 text-[12px] text-slate-600"
          >
            {l}
          </div>
        ))}
      </div>
    </div>
  );
}
