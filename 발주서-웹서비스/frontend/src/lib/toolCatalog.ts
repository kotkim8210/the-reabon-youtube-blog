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
    title: '명이나물+애플초당옥수수+초당옥수수+망고수박+수박+성주참외+신비복숭아+미니밤호박+거반도납작복숭아+대극천복숭아+백도딱딱이복숭아',
    description: '쥬얼리프룻 발주서 생성(쿠팡+토스 통합) + 운송장번호 입력 · 미니밤호박 3·5·10kg·거반도 납작복숭아(500g·1·2kg)·대극천 복숭아(소과 1kg) 포함',
    icon: '🌿',
    color: 'green',
    kind: 'unified',
  },
  {
    id: 'kolrabi-unified',
    title: '콜라비·미니밤호박 1kg·홍감자(제주다팜)',
    description: '콜라비·미니밤호박 1kg·홍감자 제주다팜 발주서 생성 + 운송장번호 입력 · 홍감자 매칭: 중1kg→중2kg, 대3kg→특3kg, 대5kg→특5kg (미니밤호박 3·5·10kg·초당옥수수·애플초당옥수수·성주참외는 명이나물 메뉴)',
    icon: '🥬',
    color: 'green',
    kind: 'unified',
  },
  {
    id: 'tomato-unified',
    title: '대저토마토·남해땅두릅·신비복숭아',
    description: '제이비티엠 발주서 생성 + 운송장번호 입력 (초당옥수수는 명이나물(쥬얼리) 메뉴로 이동)',
    icon: '🍅🍈🌿🍑',
    color: 'red',
    kind: 'unified',
  },
  {
    id: 'toss-watermelon-order',
    title: '올웨이즈 쥬얼리 발주 + 토스 운송장 등록',
    description: '올웨이즈 주문 → 쥬얼리프룻 발주서 + 토스 운송장 자동등록. (토스 주문 수집은 명이나물 메뉴로 일원화)',
    icon: '🍉',
    color: 'red',
    kind: 'order',
  },
  {
    id: 'temu-order',
    title: '테무 수박·성주참외·고구마 발주서 생성',
    description: '테무 order_export 엑셀/CSV로 수박·성주참외는 쥬얼리프룻 발주서, 고구마는 해달 발주서(한진양식)로 만들고, 거래처 송장파일을 테무 배송확인 양식으로 변환합니다.',
    icon: '🛒',
    color: 'red',
    kind: 'order',
  },
  {
    id: 'temu-tracking',
    title: '테무 송장 대량등록',
    description:
      '테무 주문목록(order_export 엑셀/CSV) + 택배 송장파일을 매칭해 "배송 확인" 업로드 템플릿(주문ID/주문상품id/수량/배송사/추적번호)을 자동 작성합니다.',
    icon: '🛒📦',
    color: 'red',
    kind: 'tracking',
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
    id: 'biseller-order',
    title: '비셀러 (LA한입갈비)',
    description: 'DeliveryList에서 한입 LA갈비 주문을 추출해 비셀러 발주서(아이티소프트 양식)를 만듭니다. 쿠팡 800g N개 → 비셀러 800G*N세트 표기로 변환.',
    icon: '🥩',
    color: 'red',
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

interface ToolOverride {
  title?: string;
  description?: string;
}

interface ToolPrefs {
  hidden: string[];   // 숨김 처리된 tool id
  deleted: string[];  // 삭제 처리된 tool id (휴지통)
  renamed: Record<string, ToolOverride>;  // 사용자 지정 이름/설명 override
  sectionTitles: Record<string, string>;  // 통합 페이지 섹션 제목 override (key별 커스텀 텍스트)
  order: string[];    // 사용자 지정 카드 표시 순서 (tool id 순서; 미포함 id는 카탈로그 순서로 뒤에)
}

const EMPTY_PREFS: ToolPrefs = { hidden: [], deleted: [], renamed: {}, sectionTitles: {}, order: [] };

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
      renamed: (parsed.renamed && typeof parsed.renamed === 'object') ? parsed.renamed : {},
      sectionTitles: (parsed.sectionTitles && typeof parsed.sectionTitles === 'object') ? parsed.sectionTitles : {},
      order: Array.isArray(parsed.order) ? parsed.order : [],
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

export function renameTool(
  userId: number | string | null | undefined,
  toolId: string,
  title: string | undefined,
  description: string | undefined,
): ToolPrefs {
  const prefs = loadToolPrefs(userId);
  const entry: ToolOverride = { ...(prefs.renamed[toolId] || {}) };
  if (title !== undefined) {
    const t = title.trim();
    if (t) entry.title = t;
    else delete entry.title;
  }
  if (description !== undefined) {
    const d = description.trim();
    if (d) entry.description = d;
    else delete entry.description;
  }
  if (Object.keys(entry).length > 0) prefs.renamed[toolId] = entry;
  else delete prefs.renamed[toolId];
  saveToolPrefs(userId, prefs);
  return prefs;
}

/** 카탈로그 기본값에 사용자 override(이름/설명)를 적용한 ToolConfig를 반환 */
export function applyToolOverride(tool: ToolConfig, prefs: ToolPrefs): ToolConfig {
  const ov = prefs.renamed[tool.id];
  if (!ov) return tool;
  return {
    ...tool,
    title: ov.title ?? tool.title,
    description: ov.description ?? tool.description,
  };
}

export function resetToolPrefs(userId: number | string | null | undefined): ToolPrefs {
  const empty: ToolPrefs = { hidden: [], deleted: [], renamed: {}, sectionTitles: {}, order: [] };
  saveToolPrefs(userId, empty);
  return empty;
}

/** 카드 표시 순서 저장 (ids 순서대로; 미포함 id는 카탈로그 순서로 뒤에 붙음) */
export function setToolOrder(
  userId: number | string | null | undefined,
  ids: string[],
): ToolPrefs {
  const prefs = loadToolPrefs(userId);
  prefs.order = ids;
  saveToolPrefs(userId, prefs);
  return prefs;
}

/** ToolConfig 배열을 사용자 지정 순서(order)대로 정렬. order에 없는 항목은 기존 카탈로그 순서로 뒤에. */
export function applyToolOrder(tools: ToolConfig[], order: string[]): ToolConfig[] {
  if (!order || order.length === 0) return tools;
  const rank = new Map(order.map((id, i) => [id, i]));
  const catalogIndex = (id: string) => TOOL_CATALOG.findIndex((t) => t.id === id);
  return [...tools].sort((a, b) => {
    const ra = rank.has(a.id) ? (rank.get(a.id) as number) : Number.MAX_SAFE_INTEGER;
    const rb = rank.has(b.id) ? (rank.get(b.id) as number) : Number.MAX_SAFE_INTEGER;
    if (ra !== rb) return ra - rb;
    return catalogIndex(a.id) - catalogIndex(b.id);
  });
}

/** 통합 페이지 섹션 제목 override 저장 (빈 값이면 기본값으로 복원) */
export function setSectionTitle(
  userId: number | string | null | undefined,
  key: string,
  title: string,
): ToolPrefs {
  const prefs = loadToolPrefs(userId);
  const t = (title || '').trim();
  if (t) prefs.sectionTitles[key] = t;
  else delete prefs.sectionTitles[key];
  saveToolPrefs(userId, prefs);
  return prefs;
}

export function getVisibleTools(userId: number | string | null | undefined): ToolConfig[] {
  const prefs = loadToolPrefs(userId);
  const visible = TOOL_CATALOG
    .filter((t) => !prefs.deleted.includes(t.id) && !prefs.hidden.includes(t.id))
    .map((t) => applyToolOverride(t, prefs));
  return applyToolOrder(visible, prefs.order);
}
