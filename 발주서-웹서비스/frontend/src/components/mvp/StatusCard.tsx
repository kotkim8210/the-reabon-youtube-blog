import { CheckCircle2, Clock, AlertTriangle, ShieldCheck } from 'lucide-react';
import type { MarketScore } from './types';

const statusColors: Record<MarketScore['status'], string> = {
  green: 'border-emerald-500 bg-emerald-50 text-emerald-700',
  yellow: 'border-amber-500 bg-amber-50 text-amber-700',
  red: 'border-rose-500 bg-rose-50 text-rose-700 shadow-lg shadow-rose-100',
  blue: 'border-blue-500 bg-blue-50 text-blue-700',
};

const statusDot: Record<MarketScore['status'], string> = {
  green: 'bg-emerald-500 animate-pulse',
  yellow: 'bg-amber-500',
  red: 'bg-rose-500 animate-bounce',
  blue: 'bg-blue-500 animate-pulse',
};

const statusIcons: Record<MarketScore['status'], typeof CheckCircle2> = {
  green: CheckCircle2,
  yellow: Clock,
  red: AlertTriangle,
  blue: ShieldCheck,
};

function StatusCard({ market }: { market: MarketScore }) {
  const StatusIcon = statusIcons[market.status];

  return (
    <div className={`p-5 rounded-2xl border-2 transition-all hover:scale-[1.02] ${statusColors[market.status]}`}>
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-lg font-bold flex items-center">
            {market.name}
            <StatusIcon
              size={16}
              className={`ml-2 ${market.status === 'red' ? 'animate-pulse' : ''}`}
            />
          </h3>
          <p className="text-2xl font-black mt-1">{market.score}점</p>
        </div>
        <div className="w-10 h-10 rounded-full flex items-center justify-center bg-white shadow-sm">
          <div className={`w-4 h-4 rounded-full ${statusDot[market.status]}`} />
        </div>
      </div>
      <div className="space-y-1">
        {market.labels.map((label, idx) => (
          <div key={idx} className="text-xs opacity-80 flex items-center italic">
            • {label}
          </div>
        ))}
      </div>
    </div>
  );
}

export default StatusCard;
