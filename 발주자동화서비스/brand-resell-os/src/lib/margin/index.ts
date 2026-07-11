// 마진 계산 엔진 (순수 함수). DB 접근 없음 — 단위 테스트 대상.
// 수수료율은 하드코딩하지 않고 fee_rules에서 주입받는다.

export interface FeeRule {
  platform: string; // 'kream' | 'poizon'
  base_fee: number; // 원 (건당 고정 수수료)
  rate_pct: number; // % (판매가 대비 정률 수수료)
}

export interface MarginInput {
  buyPrice: number; // 내 매입가 (원)
  kreamSellPrice: number; // 크림 즉시판매가 기준 판매가 (원)
  kreamFee: FeeRule;
  poizonSellPrice?: number; // 포이즌 판매가 (원, 있을 때만 시나리오 생성)
  poizonFee?: FeeRule;
  poizonWorkFee?: number; // 포이즌 작업비(검수/배송) 원, 기본 0
  isBusiness?: boolean; // 일반과세 사업자 여부 (부가세 시나리오 노출용)
}

export interface Scenario {
  key: string;
  label: string;
  settle: number; // 정산가 (원)
  margin: number; // 마진 (원)
  marginRate: number; // 마진율 (0~1)
  note?: string;
}

const won = (n: number) => Math.round(n);

/** 크림 정산가 = 판매가 - (건당 수수료 + 판매가 * 정률%) */
export function kreamSettle(sellPrice: number, fee: FeeRule): number {
  return won(sellPrice - fee.base_fee - (sellPrice * fee.rate_pct) / 100);
}

/** 포이즌 정산가 = 판매가 - (판매가 * 정률% + 작업비) */
export function poizonSettle(sellPrice: number, fee: FeeRule, workFee = 0): number {
  return won(sellPrice - (sellPrice * fee.rate_pct) / 100 - workFee);
}

/** 매입세액 공제 반영 실매입원가 (사업자, 과세매입분 10/110 환급) */
export function vatDeductedBuy(buyPrice: number): number {
  return won(buyPrice / 1.1);
}

function scenario(
  key: string,
  label: string,
  settle: number,
  buyCost: number,
  note?: string,
): Scenario {
  const margin = won(settle - buyCost);
  return {
    key,
    label,
    settle,
    margin,
    marginRate: buyCost > 0 ? margin / buyCost : 0,
    note,
  };
}

/**
 * 시나리오별 마진 계산.
 * - kream_normal: 크림 일반판매 (정산가 - 매입가)
 * - kream_vat:    사업자, 매입세액 공제 반영 (수출/영세율 관점 — 매입 환급만 반영)
 * - poizon:       포이즌 판매 (있을 때, 매입세액 공제 반영)
 */
export function calcScenarios(input: MarginInput): Scenario[] {
  const { buyPrice, kreamSellPrice, kreamFee, isBusiness } = input;
  const settleK = kreamSettle(kreamSellPrice, kreamFee);
  const out: Scenario[] = [
    scenario("kream_normal", "크림 일반판매", settleK, buyPrice),
  ];

  if (isBusiness) {
    out.push(
      scenario(
        "kream_vat",
        "크림 + 부가세환급(매입공제)",
        settleK,
        vatDeductedBuy(buyPrice),
        "사업자 매입세액 10/110 공제 가정",
      ),
    );
  }

  if (input.poizonSellPrice && input.poizonFee) {
    const settleP = poizonSettle(
      input.poizonSellPrice,
      input.poizonFee,
      input.poizonWorkFee ?? 0,
    );
    const buyCost = isBusiness ? vatDeductedBuy(buyPrice) : buyPrice;
    out.push(
      scenario(
        "poizon",
        "포이즌 판매",
        settleP,
        buyCost,
        isBusiness ? "수출 영세율 → 매입 환급 반영" : undefined,
      ),
    );
  }

  return out;
}

/** 소진 예상 개월 = 총매물 / 월판매량 (판매량 0이면 null) */
export function sellThroughMonths(
  totalListings: number | null,
  monthlySales: number | null,
): number | null {
  if (!totalListings || !monthlySales || monthlySales <= 0) return null;
  return totalListings / monthlySales;
}
