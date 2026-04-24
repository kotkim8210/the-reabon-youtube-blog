import type { MarketScore, Order, InventoryAlert, CsInquiry } from './types';

export const MARKET_SCORES: MarketScore[] = [
  { id: 'coupang', name: '쿠팡', score: 98, status: 'green', labels: ['로켓프레시 준수', '낮은 파손율'] },
  { id: 'naver', name: '네이버', score: 85, status: 'yellow', labels: ['CS 응답 지연', '신선배송 독촉'] },
  { id: 'gmarket', name: '지마켓', score: 62, status: 'red', labels: ['배송 지연 건수 급증', '24시간 내 미답변 5건'] },
  { id: 'toss', name: '토스', score: 92, status: 'blue', labels: ['공동구매 유입 급증', '결제 전환율 우수'] },
];

export const RECENT_ORDERS: Order[] = [
  { id: 'O123', market: '쿠팡', product: '프리미엄 고당도 사과 5kg', price: 29800, status: '신규주문', time: '10분 전' },
  { id: 'O124', market: '네이버', product: '산지직송 완도 전복 1kg', price: 45000, status: '배송준비', time: '1시간 전' },
  { id: 'O127', market: '지마켓', product: '경북 의성 저탄소 자두 2kg', price: 21000, status: '배송지연', time: '1.5시간 전' },
  { id: 'O125', market: '토스', product: '경북 영주 꿀고구마 3kg', price: 18900, status: '신규주문', time: '2시간 전' },
];

export const INVENTORY_ALERTS: InventoryAlert[] = [
  { name: '고당도 샤인머스캣 2kg', stock: 8, status: 'critical', trend: 'down' },
  { name: 'GAP 인증 성주 참외 3kg', stock: 15, status: 'warning', trend: 'down' },
];

export const CS_INQUIRIES: CsInquiry[] = [
  { market: '지마켓', type: '환불요청', content: '사과가 아직도 안 왔어요! 환불해주세요.', time: '5분 전', urgent: true },
  { market: '지마켓', type: '배송문의', content: '어제 발송하신 거 맞나요?', time: '20분 전', urgent: true },
  { market: '토스', type: '파손문의', content: '박스가 훼손되어 도착했습니다.', time: '1시간 전', urgent: false },
];
