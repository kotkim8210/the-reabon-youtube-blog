export const won = (n: number | null | undefined) =>
  n == null ? "-" : n.toLocaleString("ko-KR") + "원";

export const pct = (r: number | null | undefined) =>
  r == null ? "-" : (r * 100).toFixed(1) + "%";

export const months = (m: number | null) =>
  m == null ? "-" : m.toFixed(1) + "개월";
