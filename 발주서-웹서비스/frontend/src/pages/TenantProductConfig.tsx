import { useState, useEffect, FormEvent } from 'react';
import {
  fetchTemplates, uploadTemplate, deleteTemplate,
  fetchUserProducts, createUserProduct, updateUserProduct, deleteUserProduct,
  analyzeDelivery,
  TemplateInfo, UserProduct, ProductInput,
} from '../api';

interface OptionForm {
  coupang_option_keyword: string;
  vendor_option_name: string;
  template_target_cell: string;
  unit_price_krw: string;
}

interface AnalyzedItem { name: string; count: number }
interface AnalyzeResult { products: AnalyzedItem[]; options: AnalyzedItem[] }

const emptyOption: OptionForm = {
  coupang_option_keyword: '',
  vendor_option_name: '',
  template_target_cell: '',
  unit_price_krw: '',
};

/* ── 색상 팔레트 ──────────────────────────────────────────────── */
const CHIP_COLORS = [
  'bg-blue-50 text-blue-700 border-blue-200',
  'bg-violet-50 text-violet-700 border-violet-200',
  'bg-emerald-50 text-emerald-700 border-emerald-200',
  'bg-amber-50 text-amber-700 border-amber-200',
  'bg-rose-50 text-rose-700 border-rose-200',
  'bg-cyan-50 text-cyan-700 border-cyan-200',
];

function chipColor(i: number) { return CHIP_COLORS[i % CHIP_COLORS.length]; }

/* ── 상품 폼 컴포넌트 ─────────────────────────────────────────── */
function ProductForm({
  templates,
  analyzed,
  initial,
  onSubmit,
  onCancel,
}: {
  templates: TemplateInfo[];
  analyzed: AnalyzeResult | null;
  initial?: UserProduct;
  onSubmit: (input: ProductInput) => Promise<void>;
  onCancel: () => void;
}) {
  const [label, setLabel] = useState(initial?.product_label ?? '');
  const [keyword, setKeyword] = useState(initial?.coupang_product_keyword ?? '');
  const [templateId, setTemplateId] = useState<number | null>(initial?.template_id ?? null);
  const [pattern, setPattern] = useState(initial?.output_filename_pattern ?? '{label}_{date}.xlsx');
  const [options, setOptions] = useState<OptionForm[]>(
    initial?.options?.length
      ? initial.options.map(o => ({
          coupang_option_keyword: o.coupang_option_keyword,
          vendor_option_name: o.vendor_option_name,
          template_target_cell: o.template_target_cell ?? '',
          unit_price_krw: String(o.unit_price_krw ?? 0),
        }))
      : [{ ...emptyOption }]
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const addOption = () => setOptions([...options, { ...emptyOption }]);
  const removeOption = (i: number) => setOptions(options.filter((_, idx) => idx !== i));
  const updateOption = (i: number, field: keyof OptionForm, value: string) => {
    const copy = [...options];
    copy[i] = { ...copy[i], [field]: value };
    setOptions(copy);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!label.trim() || !keyword.trim()) { setErr('상품명과 키워드를 입력하세요.'); return; }
    const valid = options.filter(o => o.coupang_option_keyword.trim());
    if (!valid.length) { setErr('최소 1개의 옵션을 입력하세요.'); return; }
    setBusy(true); setErr('');
    try {
      await onSubmit({
        product_label: label,
        coupang_product_keyword: keyword,
        template_id: templateId,
        output_filename_pattern: pattern,
        options: valid.map(o => ({
          coupang_option_keyword: o.coupang_option_keyword,
          vendor_option_name: o.vendor_option_name,
          template_target_cell: o.template_target_cell || null,
          unit_price_krw: Number(o.unit_price_krw) || 0,
        })),
      });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : '저장 실패');
    } finally { setBusy(false); }
  };

  const productSuggestions = analyzed?.products.slice(0, 20) ?? [];
  const optionSuggestions = analyzed?.options ?? [];

  return (
    <form onSubmit={handleSubmit} className="p-5 bg-indigo-50 rounded-2xl space-y-4 border border-indigo-100">

      {/* 기본 정보 */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">상품 라벨 <span className="text-red-400">*</span></label>
          <input value={label} onChange={e => setLabel(e.target.value)}
            placeholder="예: 대저토마토"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none" />
        </div>
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">
            쿠팡 상품명 키워드 <span className="text-red-400">*</span>
          </label>
          <input value={keyword} onChange={e => setKeyword(e.target.value)}
            placeholder="DeliveryList K열에 포함된 문자"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none" />
          {/* 분석 결과 빠른 선택 */}
          {productSuggestions.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {productSuggestions.map(p => (
                <button key={p.name} type="button"
                  onClick={() => setKeyword(p.name)}
                  className={`px-2 py-0.5 rounded text-[11px] border transition-all
                    ${keyword === p.name
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'}`}>
                  {p.name}
                  <span className="text-[10px] opacity-60 ml-1">{p.count}건</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">발주서 템플릿</label>
          <select value={templateId ?? ''} onChange={e => setTemplateId(e.target.value ? Number(e.target.value) : null)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400">
            <option value="">없음 (빈 엑셀 생성)</option>
            {templates.map(t => <option key={t.id} value={t.id}>{t.template_name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">출력 파일명 패턴</label>
          <input value={pattern} onChange={e => setPattern(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
          <p className="text-[10px] text-gray-400 mt-0.5">{'{label}'} = 상품명, {'{date}'} = 날짜</p>
        </div>
      </div>

      {/* 옵션 매핑 */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-bold text-gray-700">옵션 매핑</label>
          <button type="button" onClick={addOption}
            className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">+ 옵션 추가</button>
        </div>

        {/* 헤더 */}
        <div className="hidden sm:grid grid-cols-[1fr_1fr_80px_90px_24px] gap-2 mb-1 px-0.5">
          <span className="text-[10px] font-semibold text-gray-500">쿠팡 옵션 키워드 (L열)</span>
          <span className="text-[10px] font-semibold text-gray-500">거래처 옵션명</span>
          <span className="text-[10px] font-semibold text-gray-500">셀(합산모드)</span>
          <span className="text-[10px] font-semibold text-gray-500">단가(원)</span>
          <span />
        </div>

        {options.map((opt, i) => (
          <div key={i} className="mb-2">
            <div className="grid grid-cols-[1fr_1fr_80px_90px_24px] gap-2 items-center">
              <div>
                <input value={opt.coupang_option_keyword}
                  onChange={e => updateOption(i, 'coupang_option_keyword', e.target.value)}
                  placeholder="예: 1kg, 소, 혼합"
                  className="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400" />
              </div>
              <input value={opt.vendor_option_name}
                onChange={e => updateOption(i, 'vendor_option_name', e.target.value)}
                placeholder="발주서에 표시될 이름"
                className="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400" />
              <input value={opt.template_target_cell}
                onChange={e => updateOption(i, 'template_target_cell', e.target.value)}
                placeholder="N5"
                className="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-xs text-center focus:outline-none focus:ring-1 focus:ring-indigo-400" />
              <input type="number" min={0} value={opt.unit_price_krw}
                onChange={e => updateOption(i, 'unit_price_krw', e.target.value)}
                placeholder="0"
                className="w-full px-2 py-1.5 border border-gray-300 rounded-lg text-xs text-right focus:outline-none focus:ring-1 focus:ring-indigo-400" />
              {options.length > 1
                ? <button type="button" onClick={() => removeOption(i)}
                    className="text-red-400 hover:text-red-600 text-sm font-bold leading-none">×</button>
                : <span />}
            </div>
            {/* 옵션명 빠른 선택 (분석 결과) */}
            {optionSuggestions.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1 pl-0.5">
                {optionSuggestions.map(s => (
                  <button key={s.name} type="button"
                    onClick={() => updateOption(i, 'coupang_option_keyword', s.name)}
                    className={`px-1.5 py-0.5 rounded text-[11px] border transition-all
                      ${opt.coupang_option_keyword === s.name
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-gray-500 border-gray-200 hover:border-indigo-300'}`}>
                    {s.name}
                    <span className="opacity-50 ml-0.5">{s.count}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}

        <p className="text-[10px] text-gray-400 mt-1.5">
          <strong>셀 비움</strong> = 행 추가 모드 (고객별 발주서)&nbsp;·&nbsp;
          <strong>셀 입력(예:N5)</strong> = 합산 모드 (수량만 기재)&nbsp;·&nbsp;
          <span className="text-emerald-600">단가 입력 시 발주서 단가 관리에 활용</span>
        </p>
      </div>

      {err && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{err}</p>}

      <div className="flex gap-2">
        <button type="submit" disabled={busy}
          className="flex-1 py-2 bg-indigo-600 text-white rounded-xl text-sm font-semibold hover:bg-indigo-700 disabled:opacity-50">
          {busy ? '저장 중…' : (initial ? '수정 저장' : '상품 추가')}
        </button>
        <button type="button" onClick={onCancel}
          className="px-5 py-2 border border-gray-300 text-gray-600 rounded-xl text-sm hover:bg-gray-50">
          취소
        </button>
      </div>
    </form>
  );
}

/* ── 메인 컴포넌트 ────────────────────────────────────────────── */
function TenantProductConfig() {
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [products, setProducts] = useState<UserProduct[]>([]);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);

  // DeliveryList 분석
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzed, setAnalyzed] = useState<AnalyzeResult | null>(null);
  const [analyzeFilename, setAnalyzeFilename] = useState('');

  // 상품 추가/수정 폼
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingProduct, setEditingProduct] = useState<UserProduct | null>(null);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [t, p] = await Promise.all([fetchTemplates(), fetchUserProducts()]);
      setTemplates(t.templates);
      setProducts(p.products);
    } catch { setError('데이터 로드 실패'); }
  };

  /* 템플릿 업로드 */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setUploading(true); setError('');
    try { await uploadTemplate(file); await loadData(); }
    catch (err) { setError(err instanceof Error ? err.message : '업로드 실패'); }
    finally { setUploading(false); e.target.value = ''; }
  };

  /* DeliveryList 분석 */
  const handleAnalyze = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setAnalyzing(true); setError('');
    try {
      const result = await analyzeDelivery(file);
      setAnalyzed(result);
      setAnalyzeFilename(file.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : '분석 실패');
    } finally { setAnalyzing(false); e.target.value = ''; }
  };

  /* 상품 추가 */
  const handleCreate = async (input: ProductInput) => {
    await createUserProduct(input);
    setShowAddForm(false);
    await loadData();
  };

  /* 상품 수정 */
  const handleUpdate = async (input: ProductInput) => {
    if (!editingProduct) return;
    await updateUserProduct(editingProduct.id, input);
    setEditingProduct(null);
    await loadData();
  };

  /* 상품 삭제 */
  const handleDelete = async (id: number) => {
    if (!confirm('삭제하시겠습니까?')) return;
    try { await deleteUserProduct(id); await loadData(); }
    catch { setError('삭제 실패'); }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-indigo-600">Setup</p>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">상품/양식 설정</h1>
        <p className="mt-2 text-sm leading-6 text-gray-500">
          사용자별로 거래처 발주서 양식과 쿠팡 상품·옵션 매칭을 저장합니다. 이 설정이 그대로 내 발주 자동화에 적용됩니다.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600">{error}</div>
      )}

      {/* ── STEP 1: DeliveryList 분석 ─────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6">
        <div className="flex items-start gap-4">
          <div className="w-8 h-8 rounded-full bg-indigo-600 text-white text-sm font-bold flex items-center justify-center shrink-0">1</div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-bold text-gray-800 mb-0.5">쿠팡 DeliveryList 분석 <span className="text-xs font-normal text-gray-400">(선택)</span></h3>
            <p className="text-xs text-gray-500 mb-3">
              DeliveryList 엑셀을 올리면 상품명·옵션명을 자동으로 읽어서 아래 설정 폼에서 클릭으로 선택할 수 있습니다.
              매번 일일이 입력하지 않아도 됩니다.
            </p>

            {analyzed ? (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xs text-emerald-600 font-semibold">✓ 분석 완료: {analyzeFilename}</span>
                  <button onClick={() => { setAnalyzed(null); setAnalyzeFilename(''); }}
                    className="text-xs text-gray-400 hover:text-gray-600 underline">초기화</button>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-[11px] font-bold text-gray-500 mb-1.5">상품명 (K열) — {analyzed.products.length}종</p>
                    <div className="flex flex-wrap gap-1">
                      {analyzed.products.slice(0, 15).map((p, i) => (
                        <span key={p.name} className={`px-2 py-0.5 rounded text-[11px] border ${chipColor(i)}`}>
                          {p.name} <span className="opacity-50">{p.count}</span>
                        </span>
                      ))}
                      {analyzed.products.length > 15 && (
                        <span className="text-[11px] text-gray-400">+{analyzed.products.length - 15}개 더</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <p className="text-[11px] font-bold text-gray-500 mb-1.5">옵션명 (L열) — {analyzed.options.length}종</p>
                    <div className="flex flex-wrap gap-1">
                      {analyzed.options.slice(0, 20).map((o, i) => (
                        <span key={o.name} className={`px-2 py-0.5 rounded text-[11px] border ${chipColor(i)}`}>
                          {o.name} <span className="opacity-50">{o.count}</span>
                        </span>
                      ))}
                      {analyzed.options.length > 20 && (
                        <span className="text-[11px] text-gray-400">+{analyzed.options.length - 20}개 더</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <label className={`inline-flex items-center gap-2 px-4 py-2 bg-white border border-dashed border-indigo-300 text-indigo-600 rounded-xl text-sm font-medium cursor-pointer hover:bg-indigo-50 transition ${analyzing ? 'opacity-50' : ''}`}>
                {analyzing ? (
                  <><svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>분석 중…</>
                ) : (
                  <><svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}><path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/></svg>DeliveryList 업로드해서 분석하기</>
                )}
                <input type="file" accept=".xlsx,.xls" onChange={handleAnalyze} className="hidden" disabled={analyzing} />
              </label>
            )}
          </div>
        </div>
      </div>

      {/* ── STEP 2: 발주서 템플릿 ─────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6">
        <div className="flex items-start gap-4">
          <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-600 text-sm font-bold flex items-center justify-center shrink-0">2</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-sm font-bold text-gray-800">발주서 템플릿</h3>
              <label className={`px-3 py-1.5 bg-white border border-gray-300 text-gray-700 rounded-lg text-xs font-medium cursor-pointer hover:bg-gray-50 ${uploading ? 'opacity-50' : ''}`}>
                {uploading ? '업로드 중…' : '+ 템플릿 업로드'}
                <input type="file" accept=".xlsx,.xls" onChange={handleUpload} className="hidden" disabled={uploading} />
              </label>
            </div>
            <p className="text-xs text-gray-500 mb-3">발주처에서 받은 엑셀 양식을 올려두면, 해당 양식에 맞춰 발주서가 자동 생성됩니다.</p>
            {templates.length === 0 ? (
              <p className="text-xs text-gray-400">업로드된 템플릿이 없습니다. (없으면 빈 엑셀로 생성)</p>
            ) : (
              <div className="space-y-2">
                {templates.map(t => (
                  <div key={t.id} className="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg">
                    <div className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                      <span className="text-sm font-medium text-gray-700">{t.template_name}</span>
                      <span className="text-xs text-gray-400">{t.uploaded_at?.slice(0, 10)}</span>
                    </div>
                    <button onClick={() => deleteTemplate(t.id).then(loadData)} className="text-xs text-red-500 hover:text-red-700">삭제</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── STEP 3: 상품 설정 ─────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6">
        <div className="flex items-start gap-4">
          <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-600 text-sm font-bold flex items-center justify-center shrink-0">3</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-sm font-bold text-gray-800">상품 설정</h3>
              {!showAddForm && !editingProduct && (
                <button onClick={() => setShowAddForm(true)}
                  className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700">
                  + 상품 추가
                </button>
              )}
            </div>
            <p className="text-xs text-gray-500 mb-4">
              쿠팡 상품명·옵션명과 발주처 옵션명을 매핑합니다.
              {analyzed ? <span className="text-indigo-600 font-medium"> 위 분석 결과를 클릭해서 빠르게 선택하세요.</span> : ''}
            </p>

            {/* 추가 폼 */}
            {showAddForm && (
              <div className="mb-6">
                <ProductForm
                  templates={templates}
                  analyzed={analyzed}
                  onSubmit={handleCreate}
                  onCancel={() => setShowAddForm(false)}
                />
              </div>
            )}

            {/* 상품 목록 */}
            {products.length === 0 && !showAddForm ? (
              <div className="text-center py-10 text-gray-400">
                <svg className="w-10 h-10 mx-auto mb-2 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10"/></svg>
                <p className="text-sm">등록된 상품이 없습니다</p>
                <p className="text-xs mt-1">위 "상품 추가" 버튼을 눌러 시작하세요</p>
              </div>
            ) : (
              <div className="space-y-3">
                {products.map(p => (
                  <div key={p.id} className="border border-gray-200 rounded-xl overflow-hidden">
                    {/* 수정 모드 */}
                    {editingProduct?.id === p.id ? (
                      <div className="p-4">
                        <ProductForm
                          templates={templates}
                          analyzed={analyzed}
                          initial={p}
                          onSubmit={handleUpdate}
                          onCancel={() => setEditingProduct(null)}
                        />
                      </div>
                    ) : (
                      <div className="p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="font-semibold text-sm text-gray-900">{p.product_label}</span>
                            <span className="text-xs bg-gray-100 text-gray-500 rounded px-1.5 py-0.5">
                              키워드: {p.coupang_product_keyword}
                            </span>
                            {p.template_id && (
                              <span className="text-xs bg-blue-50 text-blue-600 rounded px-1.5 py-0.5">
                                📄 {templates.find(t => t.id === p.template_id)?.template_name ?? '템플릿'}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <button onClick={() => { setEditingProduct(p); setShowAddForm(false); }}
                              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">수정</button>
                            <button onClick={() => handleDelete(p.id)}
                              className="text-xs text-red-500 hover:text-red-700">삭제</button>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {p.options?.map((o, i) => (
                            <span key={o.id} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs border ${chipColor(i)}`}>
                              <span className="opacity-70">{o.coupang_option_keyword}</span>
                              <svg className="w-3 h-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
                              <span className="font-semibold">{o.vendor_option_name || o.coupang_option_keyword}</span>
                              {o.template_target_cell && <span className="opacity-60 text-[10px]">[{o.template_target_cell}]</span>}
                              {o.unit_price_krw > 0 && <span className="text-emerald-600 text-[10px]">₩{o.unit_price_krw.toLocaleString()}</span>}
                            </span>
                          ))}
                        </div>
                        <p className="text-[10px] text-gray-400 mt-2">출력: {p.output_filename_pattern}</p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default TenantProductConfig;
