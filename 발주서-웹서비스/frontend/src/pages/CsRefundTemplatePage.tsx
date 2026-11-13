import { useState } from 'react';
import { Check, ClipboardCopy, Loader2, MessageSquare, Search } from 'lucide-react';

import { generateCsRefundTemplate, type CsRefundOrder, type CsRefundResponse } from '../api';

export default function CsRefundTemplatePage() {
  const [recipient, setRecipient] = useState('');
  const [note, setNote] = useState('');
  const [receivedDate, setReceivedDate] = useState('');
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CsRefundResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const run = async (orderCode?: string) => {
    if (!recipient.trim()) {
      setResult({ status: 'error', message: '수취인 성함을 입력하세요.' });
      return;
    }
    setLoading(true);
    setCopied(false);
    try {
      const res = await generateCsRefundTemplate({
        recipient: recipient.trim(),
        note: note.trim(),
        received_date: receivedDate.trim() || undefined,
        order_code: orderCode,
        days,
      });
      setResult(res);
    } catch (e) {
      setResult({ status: 'error', message: e instanceof Error ? e.message : '오류가 발생했습니다.' });
    } finally {
      setLoading(false);
    }
  };

  const copy = async () => {
    if (!result?.text) return;
    try {
      await navigator.clipboard.writeText(result.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* 클립보드 권한 없으면 사용자가 직접 선택복사 */
    }
  };

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 bg-emerald-100 rounded-xl flex items-center justify-center">
          <MessageSquare className="text-emerald-600" size={22} />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-800">CS 환불 템플릿</h1>
          <p className="text-sm text-slate-500">
            수취인 성함으로 주문을 찾아 거래처 카톡 통보 문구를 만듭니다.
          </p>
        </div>
      </div>

      {/* 입력 카드 */}
      <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm space-y-4">
        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1">수취인 성함 *</label>
          <input
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && run()}
            placeholder="예: 심현순"
            className="w-full rounded-xl border border-slate-300 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-400"
          />
        </div>

        <div>
          <label className="block text-sm font-semibold text-slate-700 mb-1">원하시는 환불비중</label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="예: 4개중 1개 변질되어 부분환불 문의"
            rows={2}
            className="w-full rounded-xl border border-slate-300 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-400"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1">수령일자</label>
            <input
              value={receivedDate}
              onChange={(e) => setReceivedDate(e.target.value)}
              placeholder="예: 7.21 (비우면 오늘)"
              className="w-full rounded-xl border border-slate-300 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-400"
            />
            <p className="text-[11px] text-slate-400 mt-1">배송조회 배송완료일 자동입력은 v2 예정</p>
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1">조회 기간(일)</label>
            <input
              type="number"
              min={1}
              max={180}
              value={days}
              onChange={(e) => setDays(Number(e.target.value) || 30)}
              className="w-full rounded-xl border border-slate-300 px-4 py-2 focus:outline-none focus:ring-2 focus:ring-emerald-400"
            />
          </div>
        </div>

        <button
          onClick={() => run()}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white rounded-xl px-6 py-2.5 font-bold shadow-lg shadow-blue-100 transition"
        >
          {loading ? <Loader2 className="animate-spin" size={18} /> : <Search size={18} />}
          {loading ? '조회 중…' : '템플릿 생성'}
        </button>
      </div>

      {/* 결과 */}
      {result?.status === 'ok' && result.text && (
        <div className="bg-white rounded-2xl border border-emerald-200 p-6 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-slate-800">거래처 카톡 붙여넣기</h2>
            <button
              onClick={copy}
              className="flex items-center gap-1.5 text-sm bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-3 py-1.5 font-semibold transition"
            >
              {copied ? <Check size={15} /> : <ClipboardCopy size={15} />}
              {copied ? '복사됨' : '복사'}
            </button>
          </div>
          <textarea
            readOnly
            value={result.text}
            rows={6}
            onFocus={(e) => e.target.select()}
            className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 font-mono text-sm leading-relaxed"
          />
          {result.order && (
            <p className="text-xs text-slate-500">
              택배사 {result.order.courier || '-'} · 상태 {result.order.status || '-'} · 주소 {result.order.address}
            </p>
          )}
        </div>
      )}

      {result?.status === 'multiple' && result.candidates && (
        <div className="bg-white rounded-2xl border border-amber-200 p-6 shadow-sm space-y-3">
          <h2 className="font-bold text-slate-800">{result.message}</h2>
          <p className="text-sm text-slate-500">주소·상품을 확인하고 맞는 주문을 선택하세요 (동명이인 방지).</p>
          <div className="space-y-2">
            {result.candidates.map((c: CsRefundOrder) => (
              <button
                key={c.order_code}
                onClick={() => run(c.order_code)}
                className="w-full text-left rounded-xl border border-slate-200 hover:border-emerald-400 hover:bg-emerald-50 px-4 py-3 transition"
              >
                <div className="font-semibold text-slate-800">{c.product || '(상품명 없음)'}</div>
                <div className="text-xs text-slate-500 mt-0.5">
                  주문 {c.order_code} · 송장 {c.tracking || '-'} · {c.courier || '-'} · {c.status || '-'}
                </div>
                <div className="text-xs text-slate-500">{c.address}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {result && (result.status === 'empty' || result.status === 'error') && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-2xl px-6 py-4 text-sm">
          {result.message || '결과가 없습니다.'}
        </div>
      )}
    </div>
  );
}
