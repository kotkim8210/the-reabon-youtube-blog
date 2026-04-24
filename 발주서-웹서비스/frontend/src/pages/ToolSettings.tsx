import { useEffect, useMemo, useState } from 'react';
import { Eye, EyeOff, Trash2, RotateCcw, RefreshCcw } from 'lucide-react';
import { useUser } from '../App';
import {
  TOOL_CATALOG,
  loadToolPrefs,
  hideTool,
  unhideTool,
  softDeleteTool,
  restoreTool,
  resetToolPrefs,
  ToolConfig,
} from '../lib/toolCatalog';

type Tab = 'active' | 'hidden' | 'deleted';

export default function ToolSettings() {
  const { user } = useUser();
  const userId = user?.user_id ?? 'anon';
  const [prefs, setPrefs] = useState(loadToolPrefs(userId));
  const [tab, setTab] = useState<Tab>('active');

  useEffect(() => {
    setPrefs(loadToolPrefs(userId));
  }, [userId]);

  const groups = useMemo(() => {
    const active: ToolConfig[] = [];
    const hidden: ToolConfig[] = [];
    const deleted: ToolConfig[] = [];
    for (const t of TOOL_CATALOG) {
      if (prefs.deleted.includes(t.id)) deleted.push(t);
      else if (prefs.hidden.includes(t.id)) hidden.push(t);
      else active.push(t);
    }
    return { active, hidden, deleted };
  }, [prefs]);

  const list = groups[tab];

  const handleHide = (id: string) => setPrefs(hideTool(userId, id));
  const handleUnhide = (id: string) => setPrefs(unhideTool(userId, id));
  const handleDelete = (id: string) => {
    if (!confirm('이 도구를 삭제 상태로 이동하시겠습니까? 휴지통에서 복원할 수 있습니다.')) return;
    setPrefs(softDeleteTool(userId, id));
  };
  const handleRestore = (id: string) => setPrefs(restoreTool(userId, id));
  const handleReset = () => {
    if (!confirm('모든 도구의 숨김/삭제 상태를 초기화하시겠습니까?')) return;
    setPrefs(resetToolPrefs(userId));
  };

  const kindLabel = (k: ToolConfig['kind']) =>
    k === 'unified' ? '통합' : k === 'order' ? '발주서' : '운송장';

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">도구 설정</h1>
          <p className="text-sm text-slate-500 mt-1">
            발주서/운송장 도구를 숨기거나 삭제할 수 있습니다. 삭제한 도구는 휴지통에서 복원할 수 있습니다.
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
            onClick={() => setTab(t.key)}
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
          list.map((t) => (
            <div key={t.id} className="flex items-center gap-4 p-4">
              <div className="text-2xl w-10 text-center">{t.icon}</div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="font-semibold text-slate-900 truncate">{t.title}</p>
                  <span className="text-[10px] font-bold tracking-wider uppercase bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
                    {kindLabel(t.kind)}
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{t.description}</p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
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
              </div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
