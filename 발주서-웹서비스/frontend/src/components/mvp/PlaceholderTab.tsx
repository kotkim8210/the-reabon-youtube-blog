import { useNavigate } from 'react-router-dom';
import { Leaf } from 'lucide-react';

function PlaceholderTab() {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center justify-center h-full text-slate-400 space-y-4 min-h-[60vh]">
      <div className="w-20 h-20 bg-slate-100 rounded-full flex items-center justify-center">
        <Leaf size={40} className="text-emerald-500" />
      </div>
      <h2 className="text-xl font-bold">센터 구축 중</h2>
      <p className="text-sm italic tracking-wide">AI가 마켓 데이터를 실시간 분석 중입니다.</p>
      <button
        onClick={() => navigate('/')}
        className="mt-4 px-6 py-2 bg-blue-600 text-white rounded-xl font-bold shadow-lg shadow-blue-100"
      >
        메인 대시보드로 돌아가기
      </button>
    </div>
  );
}

export default PlaceholderTab;
