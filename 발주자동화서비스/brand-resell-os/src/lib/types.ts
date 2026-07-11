// DB 행 타입 (Phase 1)
export type Role = "owner" | "staff" | "warehouse";
export type ParcelStatus =
  | "expected"
  | "arrived"
  | "inspecting"
  | "completed"
  | "issue";
export type ItemCondition = "ok" | "short" | "wrong" | "defect";

export interface Product {
  id: string;
  workspace_id: string;
  brand: string;
  name: string;
  style_code: string;
  category: "신발" | "의류" | "기타";
  image_url: string | null;
  created_at: string;
}

export interface MarketSnapshot {
  id: string;
  product_id: string;
  platform: "kream" | "poizon";
  size: string;
  lowest_ask: number | null;
  highest_bid: number | null;
  total_listings: number | null;
  monthly_sales: number | null;
  source: string;
  captured_at: string;
}

export interface FeeRuleRow {
  id: string;
  platform: string;
  match_label: string;
  base_fee: number;
  rate_pct: number;
  valid_from: string;
  valid_to: string | null;
  memo: string | null;
}

export interface LinkedAccount {
  id: string;
  workspace_id: string;
  platform: string;
  label: string;
  account_type: "buy" | "sell";
  grade: string | null;
  mileage: number | null;
  next_grade_gap: number | null;
}

export interface Purchase {
  id: string;
  workspace_id: string;
  account_id: string | null;
  product_id: string | null;
  raw_name: string;
  option_text: string | null;
  qty: number;
  paid_total: number;
  ship_to: string | null;
  is_personal: boolean;
  status: "ordered" | "shipping" | "delivered";
  source: string;
  ordered_at: string;
}

export interface InboundParcel {
  id: string;
  workspace_id: string;
  tracking_no: string;
  carrier: string | null;
  expected_date: string | null;
  status: ParcelStatus;
  arrived_by: string | null;
  arrived_at: string | null;
  inspected_by: string | null;
  inspected_at: string | null;
}

export interface InboundItem {
  id: string;
  parcel_id: string;
  purchase_id: string | null;
  raw_name: string;
  option_text: string | null;
  expected_qty: number;
  received_qty: number | null;
  condition: ItemCondition | null;
}
