// 하드코딩된 발주서/운송장 도구 카탈로그 + 사용자별 숨김/삭제 상태(로컬스토리지)

export interface ToolConfig {
  id: string;
  title: string;
  description: string;
  icon: string;
  color: 'green' | 'red' | 'orange' | 'blue' | 'amber';
  kind: 'unified' | 'order' | 'tracking';
}

export const TOOL_CATALOG: ToolConfig[] = [
  {
    id: 'goguma-unified',
    title: '고구마 통합 대시보드',
    description: '쿠팡 + 토스 주문 수집 → 발주서 생성 → 운송장 등록 → CS 관리까지 한 화면에서.',
    icon: '🍠',
    color: 'orange',
    kind: 'unified',
  },
  {
    id: 'chamdureup-unified',
    title: '참두릅',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🌱',
    color: 'green',
    kind: 'unified',
  },
  {
    id: 'myeongi-unified',
    title: '명이나물',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🌿',
    color: 'green',
    kind: 'unified',
  },
  {
    id: 'kolrabi-unified',
    title: '콜라비',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🥬',
    color: 'green',
    kind: 'unified',
  },
  {
    id: 'tomato-unified',
    title: '대저토마토·성주참외(중소/로얄)·남해땅두릅',
    description: '발주서 생성 + 운송장번호 입력',
    icon: '🍅🍈🌿',
    color: 'red',
    kind: 'unified',
  },
  {
    id: 'goguma-order',
    title: '고구마 발주서 생성 (수동)',
    description: 'DeliveryList에서 고구마 주문을 추출하여 해달 발주서를 생성합니다.',
    icon: '🍠',
    color: 'orange',
    kind: 'order',
  },
  {
    id: 'gaegeolmu-order',
    title: '게걸무씨앗기름 발주서 생성',
    description: 'DeliveryList에서 게걸무씨앗기름 주문을 추출하여 발주서를 생성합니다.',
    icon: '🌾',
    color: 'amber',
    kind: 'order',
  },
  {
    id: 'gaegeolmu-tracking',
    title: '게걸무씨앗기름 운송장번호 입력',
    description: '게걸무 택배발송 파일(B=운송장, C=이름)의 운송장번호를 DeliveryList에 매핑합니다. 동명이인 자동 감지.',
    icon: '🌾📦',
    color: 'amber',
    kind: 'tracking',
  },
];

// --- Per-user preferences (localStorage) ---

interface ToolPrefs {
  hidden: string[];   // 숨김 처리된 tool id
  deleted: string[];  // 삭제 처리된 tool id (휴지통)
}

const EMPTY_PREFS: ToolPrefs = { hidden: [], deleted: [] };

function prefsKey(userId: number | string | null | undefined): string {
  return `tool-prefs:${userId ?? 'anon'}`;
}

export function loadToolPrefs(userId: number | string | null | undefined): ToolPrefs {
  try {
    const raw = localStorage.getItem(prefsKey(userId));
    if (!raw) return { ...EMPTY_PREFS };
    const parsed = JSON.parse(raw);
    return {
      hidden: Array.isArray(parsed.hidden) ? parsed.hidden : [],
      deleted: Array.isArray(parsed.deleted) ? parsed.deleted : [],
    };
  } catch {
    return { ...EMPTY_PREFS };
  }
}

export function saveToolPrefs(userId: number | string | null | undefined, prefs: ToolPrefs): void {
  try {
    localStorage.setItem(prefsKey(userId), JSON.stringify(prefs));
  } catch {
    // ignore quota errors
  }
}

export function hideTool(userId: number | string | null | undefined, toolId: string): ToolPrefs {
  const prefs = loadToolPrefs(userId);
  if (!prefs.hidden.includes(toolId)) prefs.hidden.push(toolId);
  saveToolPrefs(userId, prefs);
  return prefs;
}

export function unhideTool(userId: number | string | null | undefined, toolId: string): ToolPrefs {
  const prefs = loadToolPrefs(userId);
  prefs.hidden = prefs.hidden.filter((id) => id !== toolId);
  saveToolPrefs(userId, prefs);
  return prefs;
}

export function softDeleteTool(userId: number | string | null | undefined, toolId: string): ToolPrefs {
  const prefs = loadToolPrefs(userId);
  if (!prefs.deleted.includes(toolId)) prefs.deleted.push(toolId);
  // 삭제 시 숨김 목록에서는 제거 (중복 상태 방지)
  prefs.hidden = prefs.hidden.filter((id) => id !== toolId);
  saveToolPrefs(userId, prefs);
  return prefs;
}

export function restoreTool(userId: number | string | null | undefined, toolId: string): ToolPrefs {
  const prefs = loadToolPrefs(userId);
  prefs.deleted = prefs.deleted.filter((id) => id !== toolId);
  saveToolPrefs(userId, prefs);
  return prefs;
}

export function resetToolPrefs(userId: number | string | null | undefined): ToolPrefs {
  saveToolPrefs(userId, { ...EMPTY_PREFS });
  return { ...EMPTY_PREFS };
}

export function getVisibleTools(userId: number | string | null | undefined): ToolConfig[] {
  const prefs = loadToolPrefs(userId);
  return TOOL_CATALOG.filter(
    (t) => !prefs.deleted.includes(t.id) && !prefs.hidden.includes(t.id),
  );
}
