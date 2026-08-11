export interface GogumaDateRange {
  fromDate: string;
  toDate: string;
  days: number;
}

const KOREAN_PUBLIC_HOLIDAYS_BY_YEAR: Record<number, string[]> = {
  2026: [
    '2026-01-01',
    '2026-02-16',
    '2026-02-17',
    '2026-02-18',
    '2026-03-01',
    '2026-03-02',
    '2026-05-01',
    '2026-05-05',
    '2026-05-24',
    '2026-05-25',
    '2026-06-03',
    '2026-06-06',
    '2026-08-15',
    '2026-08-17',
    '2026-09-24',
    '2026-09-25',
    '2026-09-26',
    '2026-10-03',
    '2026-10-05',
    '2026-10-09',
    '2026-12-25',
  ],
};

function toLocalDateOnly(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number): Date {
  const next = toLocalDateOnly(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function formatGogumaDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function isKoreanPublicHoliday(date: Date): boolean {
  const year = date.getFullYear();
  const holidays = KOREAN_PUBLIC_HOLIDAYS_BY_YEAR[year] || [];
  return holidays.includes(formatGogumaDate(date));
}

export function getGogumaDateRangeForDays(days: number, referenceDate = new Date()): GogumaDateRange {
  const end = toLocalDateOnly(referenceDate);
  const start = addDays(end, -(days - 1));
  return {
    fromDate: formatGogumaDate(start),
    toDate: formatGogumaDate(end),
    days,
  };
}

export function getDefaultGogumaDateRange(referenceDate = new Date()): GogumaDateRange {
  const today = toLocalDateOnly(referenceDate);

  if (today.getDay() === 1) {
    return getGogumaDateRangeForDays(4, today);
  }

  if (isKoreanPublicHoliday(addDays(today, -1))) {
    return getGogumaDateRangeForDays(3, today);
  }

  // 평일 기본은 2일(어제~오늘). 발주 마감(오전 10시) 이후 들어온 어제 주문까지 챙겨야
  // 누락이 없다. 이미 발주한 건은 '이전 발주분 자동 제외'가 걸러주므로 중복 위험 없음.
  // (2026-08-11 사용자 요청 — 종전 '오늘만'은 어제 10시 이후 주문을 놓쳤다)
  return getGogumaDateRangeForDays(2, today);
}
