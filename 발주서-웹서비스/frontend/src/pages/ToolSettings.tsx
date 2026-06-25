import { useEffect, useMemo, useState } from 'react';
import { Eye, EyeOff, Trash2, RotateCcw, RefreshCcw, Pencil, Check, X, ChevronUp, ChevronDown } from 'lucide-react';
import { useUser } from '../App';
import {
  TOOL_CATALOG,
  loadToolPrefs,
  hideTool,
  unhideTool,
  softDeleteTool,
  restoreTool,
  resetToolPrefs,
  renameTool,
  applyToolOverride,
  applyToolOrder,
  setToolOrder,
  ToolConfig,
} from '../lib/toolCatalog';

type Tab = 'active' | 'hidden' | 'deleted';

export default function ToolSettings() {
  const { user } = useUser();
  const userId = user?.user_id ?? 'anon';
  const [prefs, setPrefs] = useState(loadToolPrefs(userId));
  const [tab, setTab] = useState<Tab>('active');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDesc, setEditDesc] = useState('');

  useEffect(() => {
    setPrefs(loadToolPrefs(userId));
  }, [userId]);

  const groups = useMemo(() => {
    const active: ToolConfig[] = [];
    const hidden: ToolConfig[] = [];
    const deleted: ToolConfig[] = [];
    for (const base of TOOL_CATALOG) {
      const t = applyToolOverride(base, prefs);
      if (prefs.deleted.includes(t.id)) deleted.push(t);
      else if (prefs.hidden.includes(t.id)) hidden.push(t);
      else active.push(t);
    }
    return { active: applyToolOrder(active, prefs.order), hidden, deleted };
  }, [prefs]);

  // 활성 카드 순서 이동 (▲▼) — 현재 활성 순서를 바꿔 저장
  const moveActive = (id: string, dir: 'up' | 'down') => {
    const ids = groups.active.map((t) => t.id);
    const i = ids.indexOf(id);
    const j = dir === 'up' ? i - 1 : i + 1;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setPrefs(setToolOrder(userId, ids));
  };

  const list = groups[tab];

  const handleHide = (id: string) => setPrefs(hideTool(userId, id));
  const handleUnhide = (id: string) => setPrefs(unhideTool(userId, id));
  const handleDelete = (id: string) => {
    if (!confirm('이 도구를 삭제 상태로 이동하시겠습니까? 휴지통에서 복원할 수 있습니다.')) return;
    setPrefs(softDeleteTool(userId, id));
  };
  const handleRestore = (id: string) => setPrefs(restoreTool(userId, id));
  const handleReset = () => {
    if (!confirm('모든 도구의 숨김/삭제/이름변경을 초기화하시겠습니까?')) return;
    setPrefs(resetToolPrefs(userId));
    setEditingId(null);
  };

  const startEdit = (t: ToolConfig) => {
    setEditingId(t.id);
    setEditTitle(t.title);
    setEditDesc(t.description);
  };
  const cancelEdit = () => setEditingId(null);
  const saveEdit = (id: string) => {
    setPrefs(renameTool(userId, id, editTitle, editDesc));
    setEditingId(null);
  };
  const resetName = (id: string) => {
    setPrefs(renameTool(userId, id, '', ''));   // override 제거 → 기본 이름 복귀
    setEditingId(null);
  };

  const isRenamed = (id: string) => !!prefs.renamed[id];

  const kindLabel = (k: ToolConfig['kind']) =>
    k === 'unified' ? '통합' : k === 'order' ? '발주서' : '운송장';

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">도구 설정</h1>
          <p className="text-sm text-slate-500 mt-1">
            활성 탭에서 <strong>▲▼로 카드 순서 변경</strong>, 도구 <strong>이름·설명 변경</strong>, 숨김·삭제가 가능합니다. 변경 내용은 이 브라우저에 저장됩니다.
          </p>
        </div>
        <button
          onClick={handleReset}
          className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg px-3 py-2"
        >
          <RefreshCcw size={14} /> 전체 초기화
        </button>
      </header>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200">
        {([
          { key: 'active', label: `활성 (${groups.active.length})` },
          { key: 'hidden', label: `숨김 (${groups.hidden.length})` },
          { key: 'deleted', label: `휴지통 (${groups.deleted.length})` },
        ] as const).map((t) => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setEditingId(null); }}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
              tab === t.key
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* List */}
      <section className="bg-white rounded-xl shadow-sm divide-y divide-slate-100">
        {list.length === 0 ? (
          <div className="py-16 text-center text-slate-400 text-sm">
            {tab === 'active' && '활성 도구가 없습니다. 숨김/휴지통에서 복원하세요.'}
            {tab === 'hidden' && '숨긴 도구가 없습니다.'}
            {tab === 'deleted' && '삭제한 도구가 없습니다.'}
          </div>
        ) : (
          list.map((t, idx) => (
            <div key={t.id} className="flex items-center gap-4 p-4">
              {tab === 'active' && editingId !== t.id && (
                <div className="flex flex-col shrink-0 -my-1">
                  <button
                    onClick={() => moveActive(t.id, 'up')}
                    disabled={idx === 0}
                    title="위로"
                    className="text-slate-400 hover:text-indigo-600 disabled:opacity-30 disabled:cursor-not-allowed p-0.5"
                  >
                    <ChevronUp size={16} />
                  </button>
                  <button
                    onClick={() => moveActive(t.id, 'down')}
                    disabled={idx === list.length - 1}
                    title="아래로"
                    className="text-slate-400 hover:text-indigo-600 disabled:opacity-30 disabled:cursor-not-allowed p-0.5"
                  >
                    <ChevronDown size={16} />
                  </button>
                </div>
              )}
              <div className="text-2xl w-10 text-center shrink-0">{t.icon}</div>

              {editingId === t.id ? (
                /* 편집 모드 */
                <div className="flex-1 min-w-0 space-y-2">
                  <input
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    placeholder="도구 이름"
                    autoFocus
                    onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(t.id); if (e.key === 'Escape') cancelEdit(); }}
                    className="w-full px-3 py-1.5 border border-indigo-300 rounded-lg text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-indigo-200"
                  />
                  <input
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    placeholder="설명"
                    onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(t.id); if (e.key === 'Escape') cancelEdit(); }}
                    className="w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-200"
                  />
                </div>
              ) : (
                /* 표시 모드 */
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="font-semibold text-slate-900 truncate">{t.title}</p>
                    <span className="text-[10px] font-bold tracking-wider uppercase bg-slate-100 text-slate-600 px-2 py-0.5 rounded shrink-0">
                      {kindLabel(t.kind)}
                    </span>
                    {isRenamed(t.id) && (
                      <span className="text-[10px] font-semibold text-indigo-500 shrink-0">수정됨</span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{t.description}</p>
                </div>
              )}

              <div className="flex items-center gap-1 shrink-0">
                {editingId === t.id ? (
                  <>
                    <button
                      onClick={() => saveEdit(t.id)}
                      className="flex items-center gap-1 text-xs text-emerald-600 hover:bg-emerald-50 px-3 py-1.5 rounded-lg"
                    >
                      <Check size={14} /> 저장
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="flex items-center gap-1 text-xs text-slate-500 hover:bg-slate-100 px-3 py-1.5 rounded-lg"
                    >
                      <X size={14} /> 취소
                    </button>
                    {isRenamed(t.id) && (
                      <button
                        onClick={() => resetName(t.id)}
                        className="flex items-center gap-1 text-xs text-amber-600 hover:bg-amber-50 px-3 py-1.5 rounded-lg"
                      >
                        기본값
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    {tab !== 'deleted' && (
                      <button
                        onClick={() => startEdit(t)}
                        className="flex items-center gap-1 text-xs text-indigo-600 hover:bg-indigo-50 px-3 py-1.5 rounded-lg"
                      >
                        <Pencil size={14} /> 이름변경
                      </button>
                    )}
                    {tab === 'active' && (
                      <>
                        <button
                          onClick={() => handleHide(t.id)}
                          className="flex items-center gap-1 text-xs text-slate-600 hover:bg-slate-100 px-3 py-1.5 rounded-lg"
                        >
                          <EyeOff size={14} /> 숨기기
                        </button>
                        <button
                          onClick={() => handleDelete(t.id)}
                          className="flex items-center gap-1 text-xs text-rose-600 hover:bg-rose-50 px-3 py-1.5 rounded-lg"
                        >
                          <Trash2 size={14} /> 삭제
                        </button>
                      </>
                    )}
                    {tab === 'hidden' && (
                      <>
                        <button
                          onClick={() => handleUnhide(t.id)}
                          className="flex items-center gap-1 text-xs text-indigo-600 hover:bg-indigo-50 px-3 py-1.5 rounded-lg"
                        >
                          <Eye size={14} /> 보이기
                        </button>
                        <button
                          onClick={() => handleDelete(t.id)}
                          className="flex items-center gap-1 text-xs text-rose-600 hover:bg-rose-50 px-3 py-1.5 rounded-lg"
                        >
                          <Trash2 size={14} /> 삭제
                        </button>
                      </>
                    )}
                    {tab === 'deleted' && (
                      <button
                        onClick={() => handleRestore(t.id)}
                        className="flex items-center gap-1 text-xs text-emerald-600 hover:bg-emerald-50 px-3 py-1.5 rounded-lg"
                      >
                        <RotateCcw size={14} /> 복원
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
