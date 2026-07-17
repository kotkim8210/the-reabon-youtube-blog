const BASE_URL = import.meta.env.VITE_API_URL || '/api';

function getToken(): string | null {
  return localStorage.getItem('token');
}

function authHeaders(): HeadersInit {
  const token = getToken();
  if (token) {
    return { Authorization: `Bearer ${token}` };
  }
  return {};
}

function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const message = detail
      .map((item) => apiErrorMessage(item, ''))
      .filter(Boolean)
      .join(' / ');
    return message || fallback;
  }
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>;
    for (const key of ['message', 'msg', 'reason', 'error']) {
      if (typeof record[key] === 'string' && String(record[key]).trim()) {
        return String(record[key]);
      }
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

// --- Core API helpers ---

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: authHeaders(),
  });
  if (res.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('인증 만료');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: `API error: ${res.status}` }));
    throw new Error(apiErrorMessage(data.detail, `API error: ${res.status}`));
  }
  return res.json();
}

async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('인증 만료');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: `API error: ${res.status}` }));
    throw new Error(apiErrorMessage(data.detail, `API error: ${res.status}`));
  }
  return res.json();
}

async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// --- Auth ---

export async function checkAuthConfig(): Promise<{ auth_disabled: boolean }> {
  const res = await fetch(`${BASE_URL}/auth/config`);
  if (!res.ok) return { auth_disabled: false };
  return res.json();
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE_URL}/auth/change-password`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: '비밀번호 변경에 실패했습니다.' }));
    throw new Error(data.detail || '비밀번호 변경에 실패했습니다.');
  }
  return res.json();
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: '로그인에 실패했습니다.' }));
    throw new Error(data.detail || '로그인에 실패했습니다.');
  }

  return res.json();
}

export interface UserMe {
  authenticated: boolean;
  user_id: number | null;
  username: string | null;
  role: string | null;
  expires_at: string | null;
}

export async function fetchMe(): Promise<UserMe> {
  return apiGet<UserMe>('/auth/me');
}

// --- Admin API ---

export interface UserInfo {
  id: number;
  username: string;
  email: string | null;
  role: string;
  is_active: number;
  created_at: string;
  updated_at: string;
}

export interface BlockedIP {
  id: number;
  ip_address: string;
  user_id: number | null;
  blocked_by: number;
  reason: string;
  created_at: string;
}

export const fetchUsers = () => apiGet<{ users: UserInfo[] }>('/admin/users');
export const createUser = (username: string, password: string = '12345') =>
  apiPost<{ status: string; user_id: number }>('/admin/users', { username, password });
export async function toggleUserActive(userId: number): Promise<{ status: string; is_active: boolean }> {
  const res = await fetch(`${BASE_URL}/admin/users/${userId}/toggle`, {
    method: 'PATCH',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
export const fetchBlockedIPs = () => apiGet<{ blocked_ips: BlockedIP[] }>('/admin/blocked-ips');
export const blockIP = (ip_address: string, user_id?: number, reason?: string) =>
  apiPost<{ status: string; id: number }>('/admin/blocked-ips', { ip_address, user_id, reason });
export const unblockIP = (blockId: number) =>
  apiDelete<{ status: string }>(`/admin/blocked-ips/${blockId}`);

export async function downloadTemuKolrabiGoodsWorkbook(): Promise<ProcessResult> {
  const res = await fetch(`${BASE_URL}/admin/temu/kolrabi-goods/download`, {
    method: 'POST',
    headers: authHeaders(),
  });

  if (res.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('인증이 만료되었습니다.');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: '테무 콜라비 대량등록 엑셀 생성에 실패했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '테무 콜라비 대량등록 엑셀 생성에 실패했습니다.'));
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'TEMU_콜라비_대량상품등록_작성본.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) {
    filename = decodeURIComponent(filenameMatch[1]);
  }

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try {
      stats = JSON.parse(statsHeader);
    } catch {
      stats = null;
    }
  }

  return { blob, filename, stats };
}

// --- Tenant API ---

export interface TemplateInfo {
  id: number;
  user_id: number;
  template_name: string;
  uploaded_at: string;
}

export interface ProductOption {
  id: number;
  user_product_id: number;
  coupang_option_keyword: string;
  vendor_option_name: string;
  template_target_cell: string | null;
  unit_price_krw: number;
  created_at: string;
}

export interface UserProduct {
  id: number;
  user_id: number;
  product_label: string;
  coupang_product_keyword: string;
  template_id: number | null;
  output_filename_pattern: string;
  is_active: number;
  created_at: string;
  options: ProductOption[];
}

export interface ProductInput {
  product_label: string;
  coupang_product_keyword: string;
  template_id: number | null;
  output_filename_pattern: string;
  options: { coupang_option_keyword: string; vendor_option_name: string; template_target_cell?: string | null; unit_price_krw?: number }[];
}

export const fetchTemplates = () => apiGet<{ templates: TemplateInfo[] }>('/tenant/templates');
export const deleteTemplate = (id: number) => apiDelete<{ status: string }>(`/tenant/templates/${id}`);

export async function uploadTemplate(file: File): Promise<{ status: string; id: number; name: string }> {
  const formData = new FormData();
  formData.append('template_file', file);
  const res = await fetch(`${BASE_URL}/tenant/templates`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: '업로드 실패' }));
    throw new Error(data.detail);
  }
  return res.json();
}

export const fetchUserProducts = () => apiGet<{ products: UserProduct[] }>('/tenant/products');
export const createUserProduct = (input: ProductInput) =>
  apiPost<{ status: string; id: number }>('/tenant/products', input);
export const updateUserProduct = (id: number, input: ProductInput) => {
  return fetch(`${BASE_URL}/tenant/products/${id}`, {
    method: 'PUT',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  }).then(async (res) => {
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Error');
    return res.json();
  });
};
export const deleteUserProduct = (id: number) => apiDelete<{ status: string }>(`/tenant/products/${id}`);

export interface AnalyzedItem { name: string; count: number }
export interface AnalyzeResult { products: AnalyzedItem[]; options: AnalyzedItem[] }

export async function analyzeDelivery(file: File): Promise<AnalyzeResult> {
  const formData = new FormData();
  formData.append('delivery_file', file);
  const res = await fetch(`${BASE_URL}/tenant/analyze`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || '분석 실패');
  }
  return res.json();
}

export async function processTenantOrder(deliveryFile: File): Promise<ProcessResult> {
  const formData = new FormData();
  formData.append('delivery_file', deliveryFile);

  const res = await fetch(`${BASE_URL}/tenant/process`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '처리 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '처리 중 오류가 발생했습니다.'));
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'result.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) filename = decodeURIComponent(filenameMatch[1]);

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try { stats = JSON.parse(statsHeader); } catch { /* ignore */ }
  }

  return { blob, filename, stats };
}

export async function processTenantTracking(replyFiles: File[], deliveryFile: File): Promise<ProcessResult> {
  const formData = new FormData();
  replyFiles.forEach((file) => {
    formData.append('reply_files', file);
  });
  formData.append('delivery_file', deliveryFile);

  const res = await fetch(`${BASE_URL}/tenant/tracking`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '송장번호를 입력하지 못했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '송장번호를 입력하지 못했습니다.'));
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'tracking-result.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) filename = decodeURIComponent(filenameMatch[1]);

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try { stats = JSON.parse(statsHeader); } catch { /* ignore */ }
  }

  return { blob, filename, stats };
}

export interface ProcessResult {
  blob: Blob;
  filename: string;
  stats: Record<string, unknown> | null;
}

export interface DanharuProcessResult extends ProcessResult {
  batch_id: number;
  sync_status: string;
}

export async function processFile(
  toolId: string,
  files: Record<string, File>,
  extraValues?: Record<string, string>,
): Promise<ProcessResult> {
  // Map frontend field names to backend field names
  const fieldNameMap: Record<string, string> = {
    delivery: 'delivery_file',
    orderlist: 'orderlist_file',
    haedal: 'haedal_file',
    tomato_reply: 'tomato_reply_file',
    template: 'template_file',
    alwayz: 'alwayz_file',
    toss: 'toss_file',
    temu: 'temu_file',
    toss_export: 'toss_export_file',
    winners: 'winners_file',
    tracking: 'tracking_file',
    tracking2: 'tracking_file2',
    order_export: 'order_export_file',
  };

  const formData = new FormData();
  for (const [key, file] of Object.entries(files)) {
    const backendKey = fieldNameMap[key] || key;
    formData.append(backendKey, file);
  }
  // Append extra string values (e.g. delivery_company)
  if (extraValues) {
    for (const [key, value] of Object.entries(extraValues)) {
      formData.append(key, value);
    }
  }

  const res = await fetch(`${BASE_URL}/process/${toolId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다. 다시 로그인해주세요.');
    }
    const data = await res.json().catch(() => ({ detail: '처리 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '처리 중 오류가 발생했습니다.'));
  }

  const blob = await res.blob();

  // Parse filename from Content-Disposition header
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'result.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) {
    filename = decodeURIComponent(filenameMatch[1]);
  }

  // Parse stats from X-Stats header
  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try {
      stats = JSON.parse(statsHeader);
    } catch {
      // ignore parse errors
    }
  }

  return { blob, filename, stats };
}

export async function processTossWatermelonTracking(
  tomatoReplyFile: File
): Promise<Record<string, unknown>> {
  const formData = new FormData();
  formData.append('tomato_reply_file', tomatoReplyFile);

  const res = await fetch(`${BASE_URL}/process/toss-watermelon-tracking`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다. 다시 로그인해주세요.');
    }
    const data = await res.json().catch(() => ({ detail: '운송장 등록 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '운송장 등록 중 오류가 발생했습니다.'));
  }

  return res.json();
}

export async function mergeBatchTrackingResults(
  files: Array<{ blob: Blob; filename: string }>,
): Promise<ProcessResult> {
  const formData = new FormData();
  files.forEach(({ blob, filename }) => {
    formData.append('result_files', blob, filename);
  });

  const res = await fetch(`${BASE_URL}/process/batch-tracking-merge`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('?몄쬆??留뚮즺?섏뿀?듬땲?? ?ㅼ떆 濡쒓렇?명빐二쇱꽭??');
    }
    const data = await res.json().catch(() => ({ detail: '통합 파일 생성 중 오류가 발생했습니다.' }));
    throw new Error(data.detail || '통합 파일 생성 중 오류가 발생했습니다.');
  }

  const blob = await res.blob();

  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'result.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) {
    filename = decodeURIComponent(filenameMatch[1]);
  }

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try {
      stats = JSON.parse(statsHeader);
    } catch {
      // ignore parse errors
    }
  }

  return { blob, filename, stats };
}

export async function processGogumaAuto(
  fromDate: string,
  toDate: string,
  includeToss = false,
  opts?: { temuFile?: File | null; alwayzFile?: File | null; sendEmail?: boolean; excludeIssued?: boolean },
): Promise<ProcessResult> {
  const formData = new FormData();
  formData.append('from_date', fromDate);
  formData.append('to_date', toDate);
  formData.append('include_toss', includeToss ? 'true' : 'false');
  formData.append('send_email', opts?.sendEmail ? 'true' : 'false');
  formData.append('exclude_issued', opts?.excludeIssued === false ? 'false' : 'true');
  if (opts?.temuFile) {
    formData.append('temu_file', opts.temuFile);
  }
  if (opts?.alwayzFile) {
    formData.append('alwayz_file', opts.alwayzFile);
  }
  const res = await fetch(`${BASE_URL}/process/goguma-auto`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다. 다시 로그인해주세요.');
    }
    const data = await res.json().catch(() => ({ detail: '처리 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '처리 중 오류가 발생했습니다.'));
  }

  const blob = await res.blob();

  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'result.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) {
    filename = decodeURIComponent(filenameMatch[1]);
  }

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try {
      stats = JSON.parse(statsHeader);
    } catch {
      // ignore
    }
  }

  return { blob, filename, stats };
}

export async function sendOrderEmailFiles(
  files: File[],
): Promise<{ status: string; to?: string; subject?: string; files?: string[] }> {
  const formData = new FormData();
  for (const f of files) {
    formData.append('files', f);
  }
  const res = await fetch(`${BASE_URL}/process/send-order-email`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다. 다시 로그인해주세요.');
    }
    throw new Error(apiErrorMessage((data as { detail?: unknown }).detail, '이메일 발송에 실패했습니다.'));
  }
  return data as { status: string; to?: string; subject?: string; files?: string[] };
}

export async function processDanharuOrder(
  deliveryFile: File,
  templateFile?: File | null,
): Promise<DanharuProcessResult> {
  const formData = new FormData();
  formData.append('delivery_file', deliveryFile);
  if (templateFile) {
    formData.append('template_file', templateFile);
  }

  const res = await fetch(`${BASE_URL}/automation/process/danharu`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '발주서를 생성하지 못했습니다.' }));
    throw new Error(data.detail || '발주서를 생성하지 못했습니다.');
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'danharu-order.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) {
    filename = decodeURIComponent(filenameMatch[1]);
  }

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try {
      stats = JSON.parse(statsHeader);
    } catch {
      stats = null;
    }
  }

  return {
    blob,
    filename,
    stats,
    batch_id: Number(res.headers.get('X-Batch-Id') || 0),
    sync_status: res.headers.get('X-Sync-Status') || 'local_only',
  };
}

export async function processDanharuTracking(
  replyFiles: File | File[],
  deliveryFile: File,
): Promise<ProcessResult> {
  const formData = new FormData();
  const files = Array.isArray(replyFiles) ? replyFiles : [replyFiles];
  for (const f of files) {
    formData.append('reply_files', f);
  }
  formData.append('delivery_file', deliveryFile);

  const res = await fetch(`${BASE_URL}/automation/tracking/unified`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('?몄쬆??留뚮즺?섏뿀?듬땲??');
    }
    const data = await res.json().catch(() => ({ detail: '운송장번호를 입력하지 못했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '운송장번호를 입력하지 못했습니다.'));
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'danharu-tracking.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) {
    filename = decodeURIComponent(filenameMatch[1]);
  }

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try {
      stats = JSON.parse(statsHeader);
    } catch {
      stats = null;
    }
  }

  return { blob, filename, stats };
}

// --- Goguma Tracking API ---

export interface TrackingApiResultItem {
  order_id: string;
  name: string;
  tracking?: string;
  status: 'success' | 'fail' | 'skip';
  message: string;
}

export interface TrackingApiResult {
  haedal_entries: number;
  coupang_orders: number;
  success: number;
  fail: number;
  skip: number;
  results: TrackingApiResultItem[];
}

export async function processGogumaTrackingApi(
  haedalFile: File
): Promise<TrackingApiResult> {
  const formData = new FormData();
  formData.append('haedal_file', haedalFile);

  const res = await fetch(`${BASE_URL}/process/goguma-tracking-api`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '처리 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '처리 중 오류가 발생했습니다.'));
  }

  return res.json();
}

// --- Toss Auto ---

export async function processTossOrder(
  fromDate: string,
  toDate: string
): Promise<ProcessResult> {
  const res = await fetch(`${BASE_URL}/process/toss-order`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_date: fromDate, to_date: toDate }),
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '처리 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '처리 중 오류가 발생했습니다.'));
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'result.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) filename = decodeURIComponent(filenameMatch[1]);

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try { stats = JSON.parse(statsHeader); } catch { /* ignore */ }
  }

  return { blob, filename, stats };
}

export async function processTossTrackingApi(
  haedalFile: File
): Promise<TrackingApiResult> {
  const formData = new FormData();
  formData.append('haedal_file', haedalFile);

  const res = await fetch(`${BASE_URL}/process/toss-tracking-api`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '처리 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '처리 중 오류가 발생했습니다.'));
  }

  return res.json();
}

export async function processDaangnOrder(text: string): Promise<ProcessResult> {
  const formData = new FormData();
  formData.append('text', text);

  const res = await fetch(`${BASE_URL}/process/daangn-order`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '처리 중 오류가 발생했습니다.' }));
    throw new Error(apiErrorMessage(data.detail, '처리 중 오류가 발생했습니다.'));
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = '당근_쥬얼리프룻_발주.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) filename = decodeURIComponent(filenameMatch[1]);

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try { stats = JSON.parse(statsHeader); } catch { /* ignore */ }
  }

  return { blob, filename, stats };
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export type BrowserSaveFileHandle = {
  createWritable: () => Promise<{
    write: (data: Blob) => Promise<void>;
    close: () => Promise<void>;
  }>;
};

export async function chooseExcelSaveFile(
  suggestedName: string,
): Promise<{ handle: BrowserSaveFileHandle | null; supported: boolean; canceled: boolean }> {
  const picker = (window as Window & {
    showSaveFilePicker?: (options: {
      suggestedName?: string;
      types?: Array<{
        description: string;
        accept: Record<string, string[]>;
      }>;
    }) => Promise<BrowserSaveFileHandle>;
  }).showSaveFilePicker;

  if (!picker) {
    return { handle: null, supported: false, canceled: false };
  }

  try {
    const handle = await picker({
      suggestedName,
      types: [
        {
          description: 'Excel workbook',
          accept: {
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
          },
        },
      ],
    });
    return { handle, supported: true, canceled: false };
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      return { handle: null, supported: true, canceled: true };
    }
    if (error instanceof DOMException && ['SecurityError', 'NotAllowedError'].includes(error.name)) {
      return { handle: null, supported: false, canceled: false };
    }
    throw error;
  }
}

export async function saveBlobToFileHandle(blob: Blob, handle: BrowserSaveFileHandle): Promise<void> {
  const writable = await handle.createWritable();
  await writable.write(blob);
  await writable.close();
}

// Dashboard
export const fetchRiskScores = () => apiGet<{ scores: RiskScoreData[] }>('/dashboard/risk-scores');
export const fetchRecentOrders = () => apiGet<{ orders: OrderData[] }>('/dashboard/recent-orders');
export const fetchInventoryAlerts = () => apiGet<{ alerts: InventoryAlertData[] }>('/dashboard/inventory-alerts');
export const fetchDashboardSummary = () => apiGet<DashboardSummaryData>('/dashboard/summary');
export const refreshDashboardData = () => apiPost<{ status: string; message: string }>('/dashboard/refresh');
export const fetchMyeongiSupplierPriceMonitor = () =>
  apiGet<SupplierPriceMonitorData>('/dashboard/supplier-price-monitor/myeongi');
export const fetchKolrabiSupplierPriceMonitor = () =>
  apiGet<SupplierPriceMonitorData>('/dashboard/supplier-price-monitor/kolrabi');
export const fetchSupplierPriceMonitor = (key: string) =>
  apiGet<SupplierPriceMonitorData>(`/dashboard/supplier-price-monitor/${encodeURIComponent(key)}`);

export const fetchSupplierPriceAlerts = () =>
  apiGet<SupplierPriceAlertsResponse>('/dashboard/supplier-price-alerts');

export const refreshAllSupplierPriceMonitors = () =>
  apiPost<{ status: string; results: Record<string, string> }>('/dashboard/supplier-price-monitor/refresh-all');

export async function downloadMyeongiSupplierPriceMonitorWorkbook(): Promise<ProcessResult> {
  return downloadSupplierPriceMonitorWorkbook('myeongi');
}

export async function downloadKolrabiSupplierPriceMonitorWorkbook(): Promise<ProcessResult> {
  return downloadSupplierPriceMonitorWorkbook('kolrabi');
}

export async function downloadSupplierPriceMonitorWorkbook(key: string): Promise<ProcessResult> {
  const res = await fetch(`${BASE_URL}/dashboard/supplier-price-monitor/${encodeURIComponent(key)}/download`, {
    method: 'POST',
    headers: authHeaders(),
  });

  if (!res.ok) {
    if (res.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    const data = await res.json().catch(() => ({ detail: '공급가 비교 엑셀을 생성하지 못했습니다.' }));
    throw new Error(data.detail || '공급가 비교 엑셀을 생성하지 못했습니다.');
  }

  const blob = await res.blob();
  if (blob.size === 0) {
    throw new Error('생성된 엑셀 파일이 비어 있습니다. 공급가 비교 데이터를 다시 확인해 주세요.');
  }

  const contentDisposition = res.headers.get('Content-Disposition') || '';
  let filename = 'supplier-price-monitor.xlsx';
  const filenameMatch = contentDisposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)"?/i);
  if (filenameMatch) {
    filename = decodeURIComponent(filenameMatch[1]);
  }

  let stats: Record<string, unknown> | null = null;
  const statsHeader = res.headers.get('X-Stats');
  if (statsHeader) {
    try {
      stats = JSON.parse(statsHeader);
    } catch {
      // ignore parse errors
    }
  }

  return { blob, filename, stats };
}

// Products
export const fetchProducts = () => apiGet<{ products: ProductData[] }>('/products');

// Pricing
export const fetchPricingRules = () => apiGet<{ rules: PricingRuleData[] }>('/pricing/rules');
export const createPricingRule = (rule: PricingRuleInput) => apiPost<{ status: string }>('/pricing/rules', rule);
export const deletePricingRule = (productId: number) => apiDelete<{ status: string }>(`/pricing/rules/${productId}`);
export const fetchPricingProposals = () => apiGet<{ proposals: PriceProposalData[] }>('/pricing/proposals');
export const fetchMargins = () => apiGet<{ margins: MarginData[] }>('/pricing/margins');
export const fetchPricingLog = () => apiGet<{ logs: PriceLogData[] }>('/pricing/log');

// --- Types ---

export interface RiskScoreData {
  product_id: number;
  product_name: string;
  score: number;
  level: 'red' | 'yellow' | 'green';
  stock: number;
  avg_daily_sales: number;
  days_remaining: number;
  margin_pct: number;
  labels: string[];
}

export interface OrderData {
  order_id: string;
  ordered_at: string;
  product_name: string;
  seller_product_id: number;
  quantity: number;
  sale_price: number;
  status: string;
  receiver_name: string;
}

export interface InventoryAlertData {
  product_id: number;
  product_name: string;
  stock: number;
  status: 'critical' | 'warning';
  avg_daily_sales: number;
  days_remaining: number;
}

export interface DashboardSummaryData {
  total_orders_today: number;
  total_revenue_today: number;
  total_products: number;
  critical_alerts: number;
}

export interface SupplierPriceMonitorRow {
  option_name: string;
  supplier_option_name?: string;
  sheet_name?: string;
  sheet_row: number;
  cell: string;
  spreadsheet_price: number;
  workbook_price?: number;
  comparison_basis?: 'previous_supplier_snapshot' | string;
  has_previous_snapshot?: boolean;
  supplier_price: number;
  diff: number;
  signal: 'blue' | 'red' | 'same';
  signal_label: string;
  margin?: number | null;
  margin_negative?: boolean;
}

export interface SupplierPriceMonitorData {
  key: string;
  title: string;
  supplier_name: string;
  product_name: string;
  checked_at: string;
  output_filename: string;
  total_items: number;
  changed_items: number;
  blue_count: number;
  red_count: number;
  same_count: number;
  negative_margin_count?: number;
  rows: SupplierPriceMonitorRow[];
}

export interface SupplierPriceAlertRun {
  id: number;
  run_date: string;
  monitor_key: string;
  supplier_name: string;
  product_name: string;
  status: 'ok' | 'error' | string;
  total_items: number;
  changed_items: number;
  blue_count: number;
  red_count: number;
  same_count: number;
  negative_margin_count?: number;
  output_filename: string;
  error_message: string;
  checked_at: string;
}

export interface SupplierPriceAlertsResponse {
  alerts: SupplierPriceAlertRun[];
  active_count: number;
  checked_monitors: number;
}

export interface ProductData {
  seller_product_id: number;
  product_name: string;
  sale_price: number;
  stock: number;
  status: string;
  vendor_item_id: number | null;
  category: string;
}

export interface PricingRuleData {
  id: number;
  product_id: number;
  product_name: string;
  min_margin_pct: number;
  min_price: number;
  max_price: number;
  ad_stop_threshold: number;
  active: number;
  created_at: string;
}

export interface PricingRuleInput {
  product_id: number;
  product_name?: string;
  min_margin_pct?: number;
  min_price?: number;
  max_price?: number;
  ad_stop_threshold?: number;
}

export interface PriceProposalData {
  product_id: number;
  product_name: string;
  current_price: number;
  proposed_price: number;
  current_margin_pct: number;
  proposed_margin_pct: number;
  reason: string;
  ad_stop_recommended: boolean;
}

export interface MarginData {
  product_id: number;
  product_name: string;
  sale_price: number;
  estimated_cost: number;
  margin: number;
  margin_pct: number;
  ad_stop_recommended: boolean;
  ad_stop_threshold: number;
  has_rule: boolean;
}

export interface PriceLogData {
  id: number;
  product_id: number;
  product_name: string;
  old_price: number;
  new_price: number;
  margin_before: number;
  margin_after: number;
  reason: string;
  executed_at: string;
}

// --- Toss Dashboard API ---

export interface TossOrder {
  orderId?: string;
  orderNumber?: string;
  orderProductId?: number;
  productName?: string;
  optionName?: string;
  quantity?: number;
  receiverName?: string;
  receiverPhone?: string;
  address?: string;
  detailAddress?: string;
  zipCode?: string;
  status?: string;
  orderedAt?: string;
  shippingNote?: string;
  salePrice?: number;
  [key: string]: unknown;
}

export interface TossClaim {
  orderProductId?: number;
  orderId?: string;
  productName?: string;
  optionName?: string;
  receiverName?: string;
  claimType?: string;
  claimStatus?: string;
  claimReason?: string;
  requestedAt?: string;
  [key: string]: unknown;
}

export const testTossConnection = () =>
  apiGet<{ status: string; message: string }>('/toss/connection-test');

export const fetchTossOrders = (startDate: string, endDate: string, orderStatus?: string) => {
  let path = `/toss/orders?start_date=${startDate}&end_date=${endDate}`;
  if (orderStatus) path += `&order_status=${orderStatus}`;
  return apiGet<{ orders: TossOrder[]; total: number }>(path);
};

export const fetchTossClaims = (startDate: string, endDate: string, claimType?: string) => {
  let path = `/toss/claims?start_date=${startDate}&end_date=${endDate}`;
  if (claimType) path += `&claim_type=${claimType}`;
  return apiGet<{ claims: TossClaim[]; total: number }>(path);
};

export const approveTossCancel = (orderProductId: number) =>
  apiPost<{ status: string }>('/toss/cancel/approve', { order_product_id: orderProductId });

export const rejectTossCancel = (orderProductId: number, reason: string) =>
  apiPost<{ status: string }>('/toss/cancel/reject', { order_product_id: orderProductId, reason });

export const approveTossExchange = (orderProductId: number) =>
  apiPost<{ status: string }>('/toss/exchange/approve', { order_product_id: orderProductId });

export const rejectTossExchange = (orderProductId: number, reason: string) =>
  apiPost<{ status: string }>('/toss/exchange/reject', { order_product_id: orderProductId, reason });

export const approveTossReturn = (orderProductId: number) =>
  apiPost<{ status: string }>('/toss/return/approve', { order_product_id: orderProductId });

export const rejectTossReturn = (orderProductId: number, reason: string) =>
  apiPost<{ status: string }>('/toss/return/reject', { order_product_id: orderProductId, reason });


// --- Signup & Billing ---

export async function signup(username: string, email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${BASE_URL}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: '가입에 실패했습니다.' }));
    throw new Error(data.detail || '가입에 실패했습니다.');
  }
  return res.json();
}

export interface Plan {
  id: number;
  code: string;
  name: string;
  price_krw: number;
  max_products: number | null;
  max_monthly_orders: number | null;
  features_json: string;
}

export interface BillingMe {
  subscription: {
    plan_code: string;
    status: string;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
  };
  plan: Plan | null;
  usage: { ym: string; order_count: number; event_count: number };
}

export const getPlans = () =>
  apiGet<{ plans: Plan[]; billing_enabled: boolean }>('/billing/plans');

export const getBillingConfig = () =>
  apiGet<{ client_key: string; customer_key_prefix: string }>('/billing/config');

export const getBillingMe = () =>
  apiGet<BillingMe>('/billing/me');

export const subscribePro = (authKey: string, customerKey: string) =>
  apiPost<{ status: string; plan_code: string; current_period_end: string }>(
    '/billing/subscribe',
    { auth_key: authKey, customer_key: customerKey },
  );

export const cancelSubscription = () =>
  apiPost<{ status: string; message: string }>('/billing/cancel');

export const resumeSubscription = () =>
  apiPost<{ status: string }>('/billing/resume');


export interface OrderBatchSummary {
  id: number;
  batch_name: string;
  template_name: string;
  output_filename: string;
  total_rows: number;
  total_quantity: number;
  processed_at: string;
  sync_status: string;
  sync_error: string;
}

export interface OrderAutomationOverview {
  from: string;
  to: string;
  supabase_enabled: boolean;
  totals: {
    batch_count: number;
    order_count: number;
    quantity: number;
    active_days: number;
    unique_options: number;
    avg_orders_per_batch: number;
    synced_batches: number;
    sync_errors: number;
    sync_pending: number;
  };
  trend: { ymd: string; total_qty: number }[];
  top_options: { product_name: string; supply_option_name: string; total_qty: number }[];
  recent_batches: OrderBatchSummary[];
}

export const getOrderAutomationOverview = (from: string, to: string) =>
  apiGet<OrderAutomationOverview>(`/automation/overview?from=${from}&to=${to}`);


// --- OAuth config (runtime, from backend env) ---

export interface OAuthConfig {
  kakao_client_id: string;
  google_client_id: string;
}

export const getOAuthConfig = () =>
  apiGet<OAuthConfig>('/auth/oauth-config');

// --- Social OAuth ---

async function _oauthExchange(path: string, body: Record<string, string>): Promise<LoginResponse> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: '로그인에 실패했습니다.' }));
    throw new Error(data.detail || '로그인에 실패했습니다.');
  }
  return res.json();
}

/** Kakao JS SDK access_token → app JWT */
export const loginWithKakao = (accessToken: string) =>
  _oauthExchange('/auth/kakao/token', { access_token: accessToken });

/** Google GSI credential (ID Token) → app JWT */
export const loginWithGoogle = (credential: string) =>
  _oauthExchange('/auth/google/token', { credential });

// --- 규칙 엔진 (Phase 1-B) ---

async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'PUT',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('인증 만료');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: `API error: ${res.status}` }));
    throw new Error(apiErrorMessage(data.detail, `API error: ${res.status}`));
  }
  return res.json();
}

export interface RuleSupplier {
  key: string;
  name: string;
  courier: string;
  order_cutoff: string;
  delivery_method: string;
  active: number | boolean;
}

export interface ProductRule {
  id: number;
  supplier_key: string;
  label: string;
  priority: number;
  name_keywords: string[];
  exclude_keywords: string[];
  grades: string[];
  kg_allow: string[];
  pair_map: Record<string, string>;
  extra_map: Record<string, string>;
  output_template: string;
  require_grade: number | boolean;
  require_kg: number | boolean;
  active: number | boolean;
  notes: string;
}

export type ProductRuleInput = Omit<ProductRule, 'id'>;

export interface RulePreviewResult {
  matched: boolean;
  result: {
    rule_id: number;
    label: string;
    output: string;
    grade: string;
    kg: string;
  } | null;
}

export interface RuleSimulateRow {
  row_no: number;
  product_name: string;
  option: string;
  matched: boolean;
  supplier_name: string;
  label: string;
  output: string;
}

export interface RuleSimulateResult {
  total: number;
  matched: number;
  unmatched: number;
  truncated: boolean;
  rows: RuleSimulateRow[];
  unmatched_options: { text: string; count: number }[];
}

export const fetchRuleStatus = () =>
  apiGet<{ loaded: boolean; suppliers: number; rules: number; refreshed_at: string | null }>('/rules/status');
export const refreshRules = () => apiPost<{ loaded: boolean }>('/rules/refresh');
export const fetchRuleSuppliers = () => apiGet<{ suppliers: RuleSupplier[] }>('/rules/suppliers');
export const saveRuleSupplier = (data: Omit<RuleSupplier, 'active'> & { active?: boolean }) =>
  apiPost<{ status: string; key: string }>('/rules/suppliers', data);
export const deleteRuleSupplier = (key: string) =>
  apiDelete<{ status: string }>(`/rules/suppliers/${encodeURIComponent(key)}`);
export const fetchProductRules = (supplier?: string) =>
  apiGet<{ rules: ProductRule[] }>(`/rules/products${supplier ? `?supplier=${encodeURIComponent(supplier)}` : ''}`);
export const createProductRule = (data: ProductRuleInput) =>
  apiPost<{ status: string; id: number }>('/rules/products', data);
export const updateProductRule = (id: number, data: ProductRuleInput) =>
  apiPut<{ status: string }>(`/rules/products/${id}`, data);
export const deleteProductRule = (id: number) =>
  apiDelete<{ status: string }>(`/rules/products/${id}`);
export const previewRule = (supplier_key: string, product_name: string, option_text: string) =>
  apiPost<RulePreviewResult>('/rules/preview', { supplier_key, product_name, option_text });

export async function simulateRules(file: File): Promise<RuleSimulateResult> {
  const formData = new FormData();
  formData.append('delivery_file', file);
  const res = await fetch(`${BASE_URL}/rules/simulate`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (res.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
    throw new Error('인증 만료');
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: `API error: ${res.status}` }));
    throw new Error(apiErrorMessage(data.detail, `API error: ${res.status}`));
  }
  return res.json();
}
