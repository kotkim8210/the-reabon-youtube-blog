export interface MarketScore {
  id: string;
  name: string;
  score: number;
  status: 'green' | 'yellow' | 'red' | 'blue';
  labels: string[];
}

export interface Order {
  id: string;
  market: string;
  product: string;
  price: number;
  status: string;
  time: string;
}

export interface InventoryAlert {
  name: string;
  stock: number;
  status: 'critical' | 'warning';
  trend: string;
}

export interface CsInquiry {
  market: string;
  type: string;
  content: string;
  time: string;
  urgent: boolean;
}
