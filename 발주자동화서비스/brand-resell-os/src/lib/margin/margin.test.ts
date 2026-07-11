import { describe, it, expect } from "vitest";
import {
  kreamSettle,
  poizonSettle,
  vatDeductedBuy,
  calcScenarios,
  sellThroughMonths,
  type FeeRule,
} from "./index";

const KREAM_L1: FeeRule = { platform: "kream", base_fee: 2500, rate_pct: 6.0 };
const POIZON: FeeRule = { platform: "poizon", base_fee: 0, rate_pct: 6.0 };

describe("kreamSettle", () => {
  it("레벨1(기본 2,500 + 6%) 정산가", () => {
    // 50,000 - 2,500 - 3,000 = 44,500
    expect(kreamSettle(50000, KREAM_L1)).toBe(44500);
  });
});

describe("poizonSettle", () => {
  it("6% + 작업비 반영", () => {
    // 60,000 - 3,600 - 43 = 56,357
    expect(poizonSettle(60000, POIZON, 43)).toBe(56357);
  });
});

describe("vatDeductedBuy", () => {
  it("매입세액 10/110 공제", () => {
    // 37,300 / 1.1 = 33,909.09 → 33,909
    expect(vatDeductedBuy(37300)).toBe(33909);
  });
});

describe("calcScenarios", () => {
  it("일반판매 마진 (매입 37,300, 판매 50,000, 레벨1)", () => {
    const s = calcScenarios({
      buyPrice: 37300,
      kreamSellPrice: 50000,
      kreamFee: KREAM_L1,
    });
    const normal = s.find((x) => x.key === "kream_normal")!;
    expect(normal.settle).toBe(44500); // 50000-2500-3000
    expect(normal.margin).toBe(7200); // 44500-37300
    expect(Math.round(normal.marginRate * 1000) / 10).toBe(19.3); // 19.3%
  });

  it("비사업자는 부가세 시나리오 미노출", () => {
    const s = calcScenarios({
      buyPrice: 37300,
      kreamSellPrice: 50000,
      kreamFee: KREAM_L1,
    });
    expect(s.find((x) => x.key === "kream_vat")).toBeUndefined();
  });

  it("사업자는 부가세환급 시나리오 노출 + 마진 증가", () => {
    const s = calcScenarios({
      buyPrice: 37300,
      kreamSellPrice: 50000,
      kreamFee: KREAM_L1,
      isBusiness: true,
    });
    const vat = s.find((x) => x.key === "kream_vat")!;
    expect(vat.settle).toBe(44500);
    expect(vat.margin).toBe(44500 - 33909); // 10,591
    expect(vat.margin).toBeGreaterThan(7200);
  });

  it("포이즌 시나리오 (판매가·수수료 주어질 때만)", () => {
    const s = calcScenarios({
      buyPrice: 37300,
      kreamSellPrice: 50000,
      kreamFee: KREAM_L1,
      poizonSellPrice: 60000,
      poizonFee: POIZON,
      poizonWorkFee: 43,
    });
    const p = s.find((x) => x.key === "poizon")!;
    expect(p.settle).toBe(56357);
    expect(p.margin).toBe(56357 - 37300); // 19,057
  });
});

describe("sellThroughMonths", () => {
  it("총매물/월판매 (3000/330 ≈ 9.09개월)", () => {
    expect(sellThroughMonths(3000, 330)!).toBeCloseTo(9.09, 1);
  });
  it("판매량 0이면 null", () => {
    expect(sellThroughMonths(3000, 0)).toBeNull();
  });
});
