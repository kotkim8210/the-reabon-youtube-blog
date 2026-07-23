import { useCallback, useEffect, useMemo, useState } from 'react';
import FileUpload from '../components/FileUpload';
import {
  createProductRule,
  deleteProductRule,
  deleteRuleSupplier,
  fetchProductRules,
  fetchRuleStatus,
  fetchRuleSuppliers,
  inferRules,
  previewRule,
  refreshRules,
  saveRuleSupplier,
  simulateRules,
  updateProductRule,
  type ProductRule,
  type ProductRuleInput,
  type RuleDraft,
  type RuleSimulateResult,
  type RuleSupplier,
} from '../api';

// ── 폼 직렬화 헬퍼: 콤마 리스트 / 줄단위 "키=값" 맵 ─────────────
const listToStr = (v: string[]) => (v || []).join(', ');
const strToList = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean);
const mapToStr = (m: Record<string, string>) =>
  Object.entries(m || {}).map(([k, v]) => `${k}=${v}`).join('\n');
const strToMap = (s: string): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const line of s.split('\n')) {
    const t = line.trim();
    if (!t || !t.includes('=')) continue;
    const [k, ...rest] = t.split('=');
    out[k.trim()] = rest.join('=').trim();
  }
  return out;
};

const EMPTY_RULE_FORM = {
  supplier_key: '',
  label: '',
  priority: '100',
  name_keywords: '',
  exclude_keywords: '',
  grades: '왕특, 특대, 특, 대, 중, 소',
  kg_allow: '',
  pair_map: '',
  extra_map: '',
  output_template: '',
  require_grade: true,
  require_kg: true,
  active: true,
  notes: '',
};

type RuleForm = typeof EMPTY_RULE_FORM;

const ruleToForm = (r: ProductRule): RuleForm => ({
  supplier_key: r.supplier_key,
  label: r.label,
  priority: String(r.priority ?? 100),
  name_keywords: listToStr(r.name_keywords),
  exclude_keywords: listToStr(r.exclude_keywords),
  grades: listToStr(r.grades),
  kg_allow: listToStr(r.kg_allow),
  pair_map: mapToStr(r.pair_map),
  extra_map: mapToStr(r.extra_map),
  output_template: r.output_template,
  require_grade: Boolean(r.require_grade),
  require_kg: Boolean(r.require_kg),
  active: Boolean(r.active),
  notes: r.notes || '',
});

const formToInput = (f: RuleForm): ProductRuleInput => ({
  supplier_key: f.supplier_key,
  label: f.label.trim(),
  priority: parseInt(f.priority, 10) || 100,
  name_keywords: strToList(f.name_keywords),
  exclude_keywords: strToList(f.exclude_keywords),
  grades: strToList(f.grades),
  kg_allow: strToList(f.kg_allow),
  pair_map: strToMap(f.pair_map),
  extra_map: strToMap(f.extra_map),
  output_template: f.output_template.trim(),
  require_grade: f.require_grade,
  require_kg: f.require_kg,
  active: f.active,
  notes: f.notes,
});

const EMPTY_SUPPLIER_FORM = {
  key: '',
  name: '',
  courier: '롯데택배',
  order_cutoff: '10:00',
  delivery_method: 'download',
};

function RulesEnginePage() {
  const [status, setStatus] = useState<{ loaded: boolean; suppliers: number; rules: number; refreshed_at: string | null } | null>(null);
  const [suppliers, setSuppliers] = useState<RuleSupplier[]>([]);
  const [rules, setRules] = useState<ProductRule[]>([]);
  const [supplierFilter, setSupplierFilter] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // 발주처 폼
  const [supplierForm, setSupplierForm] = useState({ ...EMPTY_SUPPLIER_FORM });
  const [supplierSaving, setSupplierSaving] = useState(false);

  // 규칙 폼
  const [ruleForm, setRuleForm] = useState<RuleForm>({ ...EMPTY_RULE_FORM });
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);
  const [ruleSaving, setRuleSaving] = useState(false);

  // 미리보기
  const [previewSupplier, setPreviewSupplier] = useState('');
  const [previewName, setPreviewName] = useState('');
  const [previewOption, setPreviewOption] = useState('');
  const [previewResult, setPreviewResult] = useState<string>('');

  // 시뮬레이터
  const [simFile, setSimFile] = useState<File | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simResult, setSimResult] = useState<RuleSimulateResult | null>(null);
  const [showMatchedRows, setShowMatchedRows] = useState(false);

  // 파일로 규칙 자동 생성 (초안)
  const [inferSupplier, setInferSupplier] = useState('');
  const [inferFile, setInferFile] = useState<File | null>(null);
  const [inferLoading, setInferLoading] = useState(false);
  const [inferDrafts, setInferDrafts] = useState<RuleDraft[]>([]);
  const [inferCovered, setInferCovered] = useState<RuleDraft[]>([]);
  const [inferProductCount, setInferProductCount] = useState<number | null>(null);
  const [addedDrafts, setAddedDrafts] = useState<Set<number>>(new Set());
  const [addingAll, setAddingAll] = useState(false);

  const loadAll = useCallback(async () => {
    setError('');
    try {
      const [st, sup, ru] = await Promise.all([
        fetchRuleStatus(),
        fetchRuleSuppliers(),
        fetchProductRules(),
      ]);
      setStatus(st);
      setSuppliers(sup.suppliers);
      setRules(ru.rules);
    } catch (e) {
      setError(e instanceof Error ? e.message : '규칙 데이터를 불러오지 못했습니다.');
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const filteredRules = useMemo(
    () => (supplierFilter ? rules.filter((r) => r.supplier_key === supplierFilter) : rules),
    [rules, supplierFilter],
  );

  const flash = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(''), 3000);
  };

  const handleSaveSupplier = async () => {
    if (!supplierForm.key.trim() || !supplierForm.name.trim()) {
      setError('발주처 key와 이름은 필수입니다. (key는 영문 소문자/숫자/하이픈)');
      return;
    }
    setSupplierSaving(true);
    setError('');
    try {
      await saveRuleSupplier({ ...supplierForm, key: supplierForm.key.trim() });
      setSupplierForm({ ...EMPTY_SUPPLIER_FORM });
      await loadAll();
      flash('발주처 저장 완료 (규칙 캐시 갱신됨)');
    } catch (e) {
      setError(e instanceof Error ? e.message : '발주처 저장 실패');
    } finally {
      setSupplierSaving(false);
    }
  };

  const handleDeleteSupplier = async (key: string) => {
    if (!window.confirm(`발주처 '${key}'를 삭제할까요? (규칙이 있으면 삭제되지 않습니다)`)) return;
    try {
      await deleteRuleSupplier(key);
      await loadAll();
      flash('발주처 삭제 완료');
    } catch (e) {
      setError(e instanceof Error ? e.message : '발주처 삭제 실패');
    }
  };

  const handleEditRule = (r: ProductRule) => {
    setEditingRuleId(r.id);
    setRuleForm(ruleToForm(r));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSaveRule = async () => {
    if (!ruleForm.supplier_key || !ruleForm.label.trim() || !ruleForm.output_template.trim() || !strToList(ruleForm.name_keywords).length) {
      setError('규칙의 발주처·라벨·매칭 키워드·출력 템플릿은 필수입니다.');
      return;
    }
    setRuleSaving(true);
    setError('');
    try {
      const payload = formToInput(ruleForm);
      if (editingRuleId != null) {
        await updateProductRule(editingRuleId, payload);
        flash(`규칙 #${editingRuleId} 수정 완료 (캐시 갱신됨)`);
      } else {
        const res = await createProductRule(payload);
        flash(`규칙 #${res.id} 추가 완료 (캐시 갱신됨)`);
      }
      setRuleForm({ ...EMPTY_RULE_FORM });
      setEditingRuleId(null);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : '규칙 저장 실패');
    } finally {
      setRuleSaving(false);
    }
  };

  const handleDeleteRule = async (id: number) => {
    if (!window.confirm(`규칙 #${id}를 삭제할까요?`)) return;
    try {
      await deleteProductRule(id);
      if (editingRuleId === id) {
        setEditingRuleId(null);
        setRuleForm({ ...EMPTY_RULE_FORM });
      }
      await loadAll();
      flash('규칙 삭제 완료');
    } catch (e) {
      setError(e instanceof Error ? e.message : '규칙 삭제 실패');
    }
  };

  const handlePreview = async () => {
    if (!previewSupplier) {
      setPreviewResult('발주처를 선택하세요.');
      return;
    }
    try {
      const res = await previewRule(previewSupplier, previewName, previewOption);
      setPreviewResult(
        res.matched && res.result
          ? `✅ 매칭 → ${res.result.output}  (규칙 #${res.result.rule_id} ${res.result.label})`
          : '❌ 미매칭 — 이 텍스트에 맞는 규칙이 없습니다.',
      );
    } catch (e) {
      setPreviewResult(e instanceof Error ? e.message : '미리보기 실패');
    }
  };

  const handleSimulate = async () => {
    if (!simFile) return;
    setSimLoading(true);
    setSimResult(null);
    setError('');
    try {
      setSimResult(await simulateRules(simFile));
    } catch (e) {
      setError(e instanceof Error ? e.message : '시뮬레이션 실패');
    } finally {
      setSimLoading(false);
    }
  };

  const handleRefresh = async () => {
    try {
      await refreshRules();
      await loadAll();
      flash('규칙 캐시 새로고침 완료');
    } catch (e) {
      setError(e instanceof Error ? e.message : '캐시 갱신 실패');
    }
  };

  const handleInfer = async () => {
    if (!inferSupplier) { setError('규칙을 붙일 발주처를 먼저 선택하세요.'); return; }
    if (!inferFile) return;
    setInferLoading(true);
    setError('');
    setInferDrafts([]);
    setInferCovered([]);
    setInferProductCount(null);
    setAddedDrafts(new Set());
    try {
      const res = await inferRules(inferFile, inferSupplier);
      setInferDrafts(res.drafts);
      setInferCovered(res.covered);
      setInferProductCount(res.product_count);
      if (res.drafts.length === 0) {
        flash(res.covered.length ? '새로 만들 규칙이 없습니다 — 업로드한 상품은 이미 규칙이 있어요.' : '상품을 찾지 못했습니다.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '규칙 초안 생성 실패');
    } finally {
      setInferLoading(false);
    }
  };

  const patchDraft = (idx: number, patch: Partial<RuleDraft>) =>
    setInferDrafts((prev) => prev.map((d, i) => (i === idx ? { ...d, ...patch } : d)));

  const addOneDraft = async (idx: number): Promise<boolean> => {
    const d = inferDrafts[idx];
    if (!d || addedDrafts.has(idx)) return false;
    if (!d.output_template.trim() || !d.name_keywords.length) {
      setError(`"${d.label}" — 매칭 키워드와 출력 템플릿을 채워주세요.`);
      return false;
    }
    await createProductRule({
      supplier_key: d.supplier_key, label: d.label, priority: d.priority,
      name_keywords: d.name_keywords, exclude_keywords: d.exclude_keywords,
      grades: d.grades, kg_allow: d.kg_allow, pair_map: d.pair_map, extra_map: d.extra_map,
      output_template: d.output_template, require_grade: d.require_grade,
      require_kg: d.require_kg, active: d.active, notes: d.notes,
    });
    setAddedDrafts((prev) => new Set(prev).add(idx));
    return true;
  };

  const handleAddDraft = async (idx: number) => {
    setError('');
    try {
      if (await addOneDraft(idx)) { await loadAll(); flash(`"${inferDrafts[idx].label}" 규칙 추가 완료`); }
    } catch (e) {
      setError(e instanceof Error ? e.message : '규칙 추가 실패');
    }
  };

  const handleAddAllDrafts = async () => {
    setAddingAll(true);
    setError('');
    let added = 0;
    try {
      for (let i = 0; i < inferDrafts.length; i += 1) {
        if (addedDrafts.has(i)) continue;
        try { if (await addOneDraft(i)) added += 1; } catch { /* keep going */ }
      }
      await loadAll();
      flash(`규칙 ${added}건 추가 완료 (캐시 갱신됨)`);
    } finally {
      setAddingAll(false);
    }
  };

  const visibleSimRows = useMemo(() => {
    if (!simResult) return [];
    const rows = showMatchedRows ? simResult.rows : simResult.rows.filter((r) => !r.matched);
    return rows.slice(0, 200);
  }, [simResult, showMatchedRows]);

  const inputCls =
    'w-full px-3 py-2 rounded-xl border border-gray-300 text-sm focus:ring-2 focus:ring-emerald-300 focus:border-emerald-400 outline-none transition-all';
  const labelCls = 'block text-xs font-semibold text-gray-600 mb-1';

  return (
    <div className="space-y-6">
      {/* 헤더 + 엔진 상태 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900">⚙️ 상품 매칭 규칙 엔진</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            상품 추가·이관을 코드 배포 없이 규칙 데이터로 처리합니다. 저장 즉시 발주 변환에 반영됩니다.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {status && (
            <span className={`px-3 py-1.5 rounded-full font-semibold ${status.loaded ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-red-50 text-red-600 border border-red-200'}`}>
              {status.loaded ? `엔진 가동 · 발주처 ${status.suppliers} · 규칙 ${status.rules}` : '엔진 미로드(하드코딩 폴백 중)'}
            </span>
          )}
          <button onClick={handleRefresh} className="px-3 py-1.5 rounded-full border border-gray-300 text-gray-600 font-semibold hover:bg-gray-50">
            캐시 새로고침
          </button>
        </div>
      </div>

      {notice && <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm font-semibold rounded-xl px-4 py-3">{notice}</div>}
      {error && <div className="bg-red-50 border border-red-200 text-red-600 text-sm font-semibold rounded-xl px-4 py-3">{error}</div>}

      {/* ⓪ 파일로 규칙 자동 생성 (초안) */}
      <div className="bg-gradient-to-br from-indigo-50 to-emerald-50 rounded-2xl shadow-sm border-2 border-indigo-200 p-6">
        <h2 className="text-base font-bold text-gray-900 mb-1">🚀 파일로 규칙 자동 생성 <span className="text-indigo-600">— 추천</span></h2>
        <p className="text-xs text-gray-600 mb-4">
          DeliveryList를 올리면 상품·옵션 패턴(등급·kg·수량)을 분석해 <b>규칙 초안</b>을 자동으로 만들어 드립니다.
          하나하나 손으로 입력할 필요 없이 <b>확인·수정 후 추가</b>만 하면 됩니다. (오매핑 방지를 위해 자동 저장은 안 하고 확인 단계를 둡니다.)
        </p>
        <div className="grid grid-cols-1 md:grid-cols-[minmax(0,220px)_1fr_auto] gap-3 md:items-end">
          <div>
            <label className={labelCls}>규칙을 붙일 발주처 *</label>
            <select className={inputCls} value={inferSupplier} onChange={(e) => setInferSupplier(e.target.value)}>
              <option value="">선택</option>
              {suppliers.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select>
          </div>
          <FileUpload label="DeliveryList 파일" file={inferFile} onFileSelect={(f) => { setInferFile(f); setInferDrafts([]); setInferCovered([]); setInferProductCount(null); }} />
          <button onClick={handleInfer} disabled={!inferFile || !inferSupplier || inferLoading}
            className="bg-indigo-600 text-white px-6 py-3 rounded-xl font-semibold text-sm hover:bg-indigo-700 disabled:opacity-50">
            {inferLoading ? '분석 중...' : '규칙 초안 만들기'}
          </button>
        </div>
        {suppliers.length === 0 && (
          <p className="mt-3 text-xs text-amber-700">먼저 아래 ① 발주처에서 거래처를 하나 등록한 뒤 다시 시도하세요.</p>
        )}

        {inferProductCount != null && (
          <div className="mt-5 space-y-4 animate-fade-in">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="px-3 py-1.5 rounded-full bg-white border border-gray-200 font-semibold">상품 {inferProductCount}종</span>
              <span className="px-3 py-1.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 font-semibold">새 규칙 초안 {inferDrafts.length}건</span>
              {inferCovered.length > 0 && <span className="px-3 py-1.5 rounded-full bg-gray-100 text-gray-500 font-semibold">이미 규칙 있음 {inferCovered.length}건</span>}
              {inferDrafts.length > 0 && (
                <button onClick={handleAddAllDrafts} disabled={addingAll || addedDrafts.size >= inferDrafts.length}
                  className="ml-auto bg-emerald-600 text-white px-4 py-2 rounded-xl font-semibold text-xs hover:bg-emerald-700 disabled:opacity-50">
                  {addingAll ? '추가 중...' : `전체 추가 (${inferDrafts.length - addedDrafts.size}건)`}
                </button>
              )}
            </div>

            {inferDrafts.map((d, idx) => {
              const added = addedDrafts.has(idx);
              return (
                <div key={idx} className={`rounded-xl border p-4 ${added ? 'border-emerald-200 bg-emerald-50/60' : 'border-gray-200 bg-white'}`}>
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <span className="text-sm font-bold text-gray-900">{d.label}</span>
                    <span className="text-xs text-gray-400">· 주문 {d.order_count}건</span>
                    {d.warnings.map((w) => (
                      <span key={w} className="text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 font-semibold">⚠ {w}</span>
                    ))}
                    {added && <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-bold">✓ 추가됨</span>}
                  </div>
                  <p className="text-xs text-gray-500 mb-3 font-mono">옵션 예: {d.sample_options.join('  /  ') || '—'}</p>
                  <div className="grid grid-cols-1 md:grid-cols-[minmax(0,160px)_1fr] gap-3">
                    <div>
                      <label className={labelCls}>매칭 키워드</label>
                      <input className={inputCls} disabled={added} value={listToStr(d.name_keywords)}
                        onChange={(e) => patchDraft(idx, { name_keywords: strToList(e.target.value) })} />
                    </div>
                    <div>
                      <label className={labelCls}>출력 템플릿 (발주서에 나갈 품목명) — {'{grade} {kg} {count}'}</label>
                      <input className={inputCls} disabled={added} value={d.output_template}
                        onChange={(e) => patchDraft(idx, { output_template: e.target.value })} />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 mt-2 text-xs text-gray-500">
                    {d.grades.length > 0 && <span>등급: {listToStr(d.grades)}</span>}
                    {d.kg_allow.length > 0 && <span>허용 kg: {listToStr(d.kg_allow)}</span>}
                    <button onClick={() => handleAddDraft(idx)} disabled={added}
                      className="ml-auto bg-emerald-600 text-white px-4 py-1.5 rounded-lg font-semibold hover:bg-emerald-700 disabled:opacity-50">
                      {added ? '추가 완료' : '+ 이 규칙 추가'}
                    </button>
                  </div>
                </div>
              );
            })}

            {inferCovered.length > 0 && (
              <details className="rounded-xl border border-gray-200 bg-white/70 p-3">
                <summary className="text-xs font-semibold text-gray-500 cursor-pointer">이미 규칙이 있는 상품 {inferCovered.length}건 (건너뜀)</summary>
                <ul className="mt-2 space-y-1">
                  {inferCovered.map((c, i) => (
                    <li key={i} className="text-xs text-gray-500">{c.label} → <span className="font-mono text-gray-700">{c.existing_output || '(기존 규칙)'}</span></li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </div>

      {/* ① 발주처 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-base font-bold text-gray-900 mb-1">① 발주처</h2>
        <p className="text-xs text-gray-500 mb-4">거래처 기본 정보 — 발송 택배사·발주 마감시각은 송장 등록/이력 기록의 기본값이 됩니다.</p>
        <div className="overflow-x-auto mb-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="py-2 pr-3">key</th><th className="py-2 pr-3">이름</th><th className="py-2 pr-3">택배사</th>
                <th className="py-2 pr-3">마감</th><th className="py-2 pr-3">전달</th><th className="py-2 pr-3">규칙 수</th><th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <tr key={s.key} className="border-b border-gray-100">
                  <td className="py-2 pr-3 font-mono text-xs">{s.key}</td>
                  <td className="py-2 pr-3 font-semibold">{s.name}</td>
                  <td className="py-2 pr-3">{s.courier}</td>
                  <td className="py-2 pr-3">{s.order_cutoff}</td>
                  <td className="py-2 pr-3">{s.delivery_method}</td>
                  <td className="py-2 pr-3">{rules.filter((r) => r.supplier_key === s.key).length}</td>
                  <td className="py-2 text-right">
                    <button onClick={() => setSupplierForm({ key: s.key, name: s.name, courier: s.courier, order_cutoff: s.order_cutoff, delivery_method: s.delivery_method })}
                      className="text-xs text-indigo-600 font-semibold mr-3 hover:underline">수정</button>
                    <button onClick={() => handleDeleteSupplier(s.key)} className="text-xs text-red-500 font-semibold hover:underline">삭제</button>
                  </td>
                </tr>
              ))}
              {suppliers.length === 0 && (
                <tr><td colSpan={7} className="py-6 text-center text-gray-400 text-sm">등록된 발주처가 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 items-end">
          <div><label className={labelCls}>key (영문)</label>
            <input className={inputCls} placeholder="jejudapam" value={supplierForm.key}
              onChange={(e) => setSupplierForm({ ...supplierForm, key: e.target.value })} /></div>
          <div><label className={labelCls}>이름</label>
            <input className={inputCls} placeholder="제주다팜" value={supplierForm.name}
              onChange={(e) => setSupplierForm({ ...supplierForm, name: e.target.value })} /></div>
          <div><label className={labelCls}>발송 택배사</label>
            <input className={inputCls} value={supplierForm.courier}
              onChange={(e) => setSupplierForm({ ...supplierForm, courier: e.target.value })} /></div>
          <div><label className={labelCls}>발주 마감</label>
            <input className={inputCls} value={supplierForm.order_cutoff}
              onChange={(e) => setSupplierForm({ ...supplierForm, order_cutoff: e.target.value })} /></div>
          <div><label className={labelCls}>전달 방식</label>
            <select className={inputCls} value={supplierForm.delivery_method}
              onChange={(e) => setSupplierForm({ ...supplierForm, delivery_method: e.target.value })}>
              <option value="download">다운로드</option>
              <option value="email">이메일</option>
            </select></div>
          <button onClick={handleSaveSupplier} disabled={supplierSaving}
            className="bg-emerald-600 text-white px-4 py-2.5 rounded-xl font-semibold text-sm hover:bg-emerald-700 disabled:opacity-50">
            {supplierSaving ? '저장 중...' : '발주처 저장'}
          </button>
        </div>
      </div>

      {/* ② 상품 매칭 규칙 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
          <h2 className="text-base font-bold text-gray-900">② 상품 매칭 규칙 {editingRuleId != null && <span className="text-indigo-600">— #{editingRuleId} 수정 중</span>}</h2>
          <select className="px-3 py-1.5 rounded-xl border border-gray-300 text-sm" value={supplierFilter} onChange={(e) => setSupplierFilter(e.target.value)}>
            <option value="">전체 발주처</option>
            {suppliers.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
          </select>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          플랫폼 상품/옵션 텍스트 → 발주 품목명. 제외 키워드는 오분류 방지(예: 신비복숭아 규칙에 '백도·거반도·대극천'), 치환맵은 "등급|kg=등급|kg" 한 줄씩(예: 중|1=중|2).
        </p>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
          <div><label className={labelCls}>발주처 *</label>
            <select className={inputCls} value={ruleForm.supplier_key} onChange={(e) => setRuleForm({ ...ruleForm, supplier_key: e.target.value })}>
              <option value="">선택</option>
              {suppliers.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select></div>
          <div><label className={labelCls}>라벨 *</label>
            <input className={inputCls} placeholder="홍감자" value={ruleForm.label} onChange={(e) => setRuleForm({ ...ruleForm, label: e.target.value })} /></div>
          <div><label className={labelCls}>우선순위(낮을수록 먼저)</label>
            <input className={inputCls} value={ruleForm.priority} onChange={(e) => setRuleForm({ ...ruleForm, priority: e.target.value })} /></div>
          <div><label className={labelCls}>출력 템플릿 * — {'{grade} {kg} {extra}'}</label>
            <input className={inputCls} placeholder="홍감자 {grade} {kg}kg" value={ruleForm.output_template} onChange={(e) => setRuleForm({ ...ruleForm, output_template: e.target.value })} /></div>
          <div><label className={labelCls}>매칭 키워드 * (콤마)</label>
            <input className={inputCls} placeholder="홍감자" value={ruleForm.name_keywords} onChange={(e) => setRuleForm({ ...ruleForm, name_keywords: e.target.value })} /></div>
          <div><label className={labelCls}>제외 키워드 (콤마)</label>
            <input className={inputCls} placeholder="수미, 감자탕" value={ruleForm.exclude_keywords} onChange={(e) => setRuleForm({ ...ruleForm, exclude_keywords: e.target.value })} /></div>
          <div><label className={labelCls}>등급 사전 (긴 것 먼저)</label>
            <input className={inputCls} value={ruleForm.grades} onChange={(e) => setRuleForm({ ...ruleForm, grades: e.target.value })} /></div>
          <div><label className={labelCls}>허용 kg (콤마, 빈칸=전체)</label>
            <input className={inputCls} placeholder="1, 3, 5" value={ruleForm.kg_allow} onChange={(e) => setRuleForm({ ...ruleForm, kg_allow: e.target.value })} /></div>
          <div className="col-span-2"><label className={labelCls}>치환맵 (줄단위 등급|kg=등급|kg)</label>
            <textarea className={`${inputCls} h-20 font-mono text-xs`} placeholder={'중|1=중|2\n대|3=특|3\n대|5=특|5'} value={ruleForm.pair_map} onChange={(e) => setRuleForm({ ...ruleForm, pair_map: e.target.value })} /></div>
          <div className="col-span-2"><label className={labelCls}>과수맵 (줄단위 등급|kg=문구, {'{extra}'} 자리)</label>
            <textarea className={`${inputCls} h-20 font-mono text-xs`} placeholder={'중과|1=5~6과 내외'} value={ruleForm.extra_map} onChange={(e) => setRuleForm({ ...ruleForm, extra_map: e.target.value })} /></div>
        </div>
        <div className="flex flex-wrap items-center gap-4 mb-4 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={ruleForm.require_grade} onChange={(e) => setRuleForm({ ...ruleForm, require_grade: e.target.checked })} /> 등급 필수</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={ruleForm.require_kg} onChange={(e) => setRuleForm({ ...ruleForm, require_kg: e.target.checked })} /> kg 필수</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={ruleForm.active} onChange={(e) => setRuleForm({ ...ruleForm, active: e.target.checked })} /> 활성</label>
          <input className={`${inputCls} flex-1 min-w-[200px]`} placeholder="메모 (이관 사유 등)" value={ruleForm.notes} onChange={(e) => setRuleForm({ ...ruleForm, notes: e.target.value })} />
          <button onClick={handleSaveRule} disabled={ruleSaving}
            className="bg-emerald-600 text-white px-5 py-2.5 rounded-xl font-semibold text-sm hover:bg-emerald-700 disabled:opacity-50">
            {ruleSaving ? '저장 중...' : editingRuleId != null ? '규칙 수정 저장' : '+ 규칙 추가'}
          </button>
          {editingRuleId != null && (
            <button onClick={() => { setEditingRuleId(null); setRuleForm({ ...EMPTY_RULE_FORM }); }}
              className="text-sm text-gray-500 font-semibold hover:underline">수정 취소</button>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
                <th className="py-2 pr-3">#</th><th className="py-2 pr-3">발주처</th><th className="py-2 pr-3">라벨</th>
                <th className="py-2 pr-3">키워드</th><th className="py-2 pr-3">제외</th><th className="py-2 pr-3">치환</th>
                <th className="py-2 pr-3">템플릿</th><th className="py-2 pr-3">상태</th><th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {filteredRules.map((r) => (
                <tr key={r.id} className={`border-b border-gray-100 ${r.active ? '' : 'opacity-40'}`}>
                  <td className="py-2 pr-3 font-mono text-xs">{r.id}</td>
                  <td className="py-2 pr-3">{suppliers.find((s) => s.key === r.supplier_key)?.name || r.supplier_key}</td>
                  <td className="py-2 pr-3 font-semibold">{r.label}</td>
                  <td className="py-2 pr-3 text-xs">{listToStr(r.name_keywords)}</td>
                  <td className="py-2 pr-3 text-xs text-red-500">{listToStr(r.exclude_keywords)}</td>
                  <td className="py-2 pr-3 text-xs font-mono">{mapToStr(r.pair_map).replace(/\n/g, ' · ')}</td>
                  <td className="py-2 pr-3 text-xs font-mono">{r.output_template}</td>
                  <td className="py-2 pr-3 text-xs">{r.active ? '활성' : '비활성'}</td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <button onClick={() => handleEditRule(r)} className="text-xs text-indigo-600 font-semibold mr-3 hover:underline">수정</button>
                    <button onClick={() => handleDeleteRule(r.id)} className="text-xs text-red-500 font-semibold hover:underline">삭제</button>
                  </td>
                </tr>
              ))}
              {filteredRules.length === 0 && (
                <tr><td colSpan={9} className="py-6 text-center text-gray-400 text-sm">규칙이 없습니다. 위 폼으로 추가하세요.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ③ 빠른 미리보기 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-base font-bold text-gray-900 mb-1">③ 빠른 미리보기</h2>
        <p className="text-xs text-gray-500 mb-4">주문 텍스트 한 건을 넣어 "어떤 발주 품목명이 되는지" 즉시 확인합니다.</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 items-end">
          <div><label className={labelCls}>발주처</label>
            <select className={inputCls} value={previewSupplier} onChange={(e) => setPreviewSupplier(e.target.value)}>
              <option value="">선택</option>
              {suppliers.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select></div>
          <div><label className={labelCls}>상품명(K열)</label>
            <input className={inputCls} placeholder="햇 홍감자 카스테라" value={previewName} onChange={(e) => setPreviewName(e.target.value)} /></div>
          <div><label className={labelCls}>옵션(L열)</label>
            <input className={inputCls} placeholder="1박스 3kg(대)" value={previewOption} onChange={(e) => setPreviewOption(e.target.value)} /></div>
          <button onClick={handlePreview}
            className="bg-indigo-600 text-white px-4 py-2.5 rounded-xl font-semibold text-sm hover:bg-indigo-700">해석하기</button>
        </div>
        {previewResult && <p className="mt-3 text-sm font-bold text-gray-800 bg-gray-50 border border-gray-200 rounded-xl px-4 py-3">{previewResult}</p>}
      </div>

      {/* ④ DeliveryList 시뮬레이터 */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-base font-bold text-gray-900 mb-1">④ DeliveryList 시뮬레이터</h2>
        <p className="text-xs text-gray-500 mb-4">
          실제 DeliveryList를 올리면 전 행에 규칙을 적용해 "이대로 발주됩니다"를 보여줍니다. 파일은 저장되지 않고 발주서도 만들지 않습니다. <b>미매칭 행이 곧 규칙 추가가 필요한 상품 목록입니다.</b>
        </p>
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 md:items-end mb-4">
          <FileUpload label="DeliveryList 파일 (미리보기 전용)" file={simFile} onFileSelect={(f) => { setSimFile(f); setSimResult(null); }} />
          <button onClick={handleSimulate} disabled={!simFile || simLoading}
            className="bg-emerald-600 text-white px-6 py-3 rounded-xl font-semibold text-sm hover:bg-emerald-700 disabled:opacity-50">
            {simLoading ? '시뮬레이션 중...' : '▶ 시뮬레이션 실행'}
          </button>
        </div>

        {simResult && (
          <div className="space-y-4 animate-fade-in">
            <div className="flex flex-wrap gap-3 text-sm">
              <span className="px-3 py-1.5 rounded-full bg-gray-100 font-semibold">총 {simResult.total}건</span>
              <span className="px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold">매칭 {simResult.matched}건</span>
              <span className={`px-3 py-1.5 rounded-full font-semibold ${simResult.unmatched ? 'bg-red-50 text-red-600 border border-red-200' : 'bg-gray-100 text-gray-500'}`}>미매칭 {simResult.unmatched}건</span>
              <label className="flex items-center gap-2 text-xs text-gray-600 ml-auto">
                <input type="checkbox" checked={showMatchedRows} onChange={(e) => setShowMatchedRows(e.target.checked)} /> 매칭 행도 표시
              </label>
            </div>

            {simResult.unmatched_options.length > 0 && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4">
                <p className="text-sm font-bold text-red-700 mb-2">미매칭 상품 (규칙 추가 필요)</p>
                <ul className="space-y-1">
                  {simResult.unmatched_options.map((u) => (
                    <li key={u.text} className="text-xs text-red-600 font-mono">{u.count}건 · {u.text}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="overflow-x-auto border border-gray-200 rounded-xl">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b border-gray-200 bg-gray-50">
                    <th className="py-2 px-3">행</th><th className="py-2 px-3">상품명/옵션</th>
                    <th className="py-2 px-3">→ 발주 품목명</th><th className="py-2 px-3">발주처</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleSimRows.map((r) => (
                    <tr key={r.row_no} className={`border-b border-gray-100 ${r.matched ? '' : 'bg-red-50'}`}>
                      <td className="py-2 px-3 font-mono text-xs">{r.row_no}</td>
                      <td className="py-2 px-3 text-xs">{r.product_name} <span className="text-gray-400">· {r.option}</span></td>
                      <td className={`py-2 px-3 text-xs font-semibold ${r.matched ? 'text-gray-800' : 'text-red-600'}`}>{r.matched ? r.output : '미매칭 — 규칙 없음'}</td>
                      <td className="py-2 px-3 text-xs">{r.supplier_name || '—'}</td>
                    </tr>
                  ))}
                  {visibleSimRows.length === 0 && (
                    <tr><td colSpan={4} className="py-5 text-center text-gray-400 text-sm">{showMatchedRows ? '표시할 행이 없습니다.' : '미매칭 행이 없습니다 — 전부 매칭됐어요 ✓'}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            {simResult.truncated && <p className="text-xs text-gray-400">표시는 상위 일부로 제한됨(집계는 전체 기준).</p>}
          </div>
        )}
      </div>
    </div>
  );
}

export default RulesEnginePage;
