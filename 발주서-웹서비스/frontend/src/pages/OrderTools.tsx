import { Link, useNavigate } from 'react-router-dom';
import { SlidersHorizontal, Layers, FileSpreadsheet, Settings, UploadCloud } from 'lucide-react';
import ProcessCard from '../components/ProcessCard';
import { useUser } from '../App';
import { getVisibleTools } from '../lib/toolCatalog';

function TenantOrderToolsLanding() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <section className="rounded-[28px] border border-indigo-100 bg-white p-8 shadow-sm">
        <p className="text-xs font-bold uppercase tracking-[0.22em] text-indigo-600">Custom Automation</p>
        <h2 className="mt-3 text-3xl font-black text-slate-950">내 상품과 거래처 양식에 맞춘 발주 자동화</h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">
          관리자 전용 고정 도구를 그대로 쓰는 방식이 아니라, 사용자마다 상품 키워드·옵션 매칭·거래처 엑셀 양식을 등록해
          같은 발주 자동화 엔진을 자기 업무에 맞게 응용합니다.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            to="/my/products"
            className="inline-flex items-center gap-2 rounded-full bg-indigo-600 px-5 py-3 text-sm font-bold text-white transition hover:bg-indigo-700"
          >
            <Settings size={16} />
            상품/양식 설정하기
          </Link>
          <Link
            to="/my/process"
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-5 py-3 text-sm font-bold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
          >
            <UploadCloud size={16} />
            DeliveryList 처리하기
          </Link>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-3">
        {[
          {
            title: '1. 거래처 양식 업로드',
            body: '각 사용자가 쓰는 발주서 엑셀 양식을 템플릿으로 등록합니다.',
          },
          {
            title: '2. 상품/옵션 매칭',
            body: '쿠팡 DeliveryList의 상품명·옵션명을 거래처가 원하는 옵션명이나 수량 입력 셀에 연결합니다.',
          },
          {
            title: '3. 발주서 자동 출력',
            body: 'DeliveryList를 올리면 등록된 설정에 맞춰 단일 엑셀 또는 ZIP으로 발주서가 생성됩니다.',
          },
        ].map((item) => (
          <article key={item.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm font-black text-slate-900">{item.title}</p>
            <p className="mt-2 text-sm leading-6 text-slate-500">{item.body}</p>
          </article>
        ))}
      </div>

      <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
        <b>운영 팁:</b> 처음에는 상품 설정 화면에서 실제 DeliveryList를 한 번 분석하면 K열 상품명과 L열 옵션명을 클릭으로 가져올 수 있어
        새 사용자도 빠르게 자기 발주 흐름을 만들 수 있습니다.
      </section>
    </div>
  );
}

function OrderTools() {
  const navigate = useNavigate();
  const { user } = useUser();
  const userId = user?.user_id ?? 'anon';
  const isAdmin = user?.role === 'admin';
  const tools = getVisibleTools(userId);

  if (!isAdmin) {
    return <TenantOrderToolsLanding />;
  }

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-800">발주서 & 운송장 도구</h2>
          <p className="text-slate-500 mt-1">사용할 도구를 선택해주세요</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/orders/settings')}
            className="flex items-center gap-1 text-xs text-slate-600 hover:bg-slate-100 border border-slate-200 rounded-lg px-3 py-2"
          >
            <SlidersHorizontal size={14} /> 도구 설정
          </button>
        </div>
      </div>

      {/* 일괄 운송장 입력 배너 */}
      <button
        onClick={() => navigate('/orders/batch-tracking')}
        className="w-full mb-5 flex items-center gap-3 bg-indigo-600 hover:bg-indigo-700
          text-white rounded-xl px-5 py-4 shadow-md shadow-indigo-200 transition-colors text-left"
      >
        <div className="w-9 h-9 bg-white/20 rounded-lg flex items-center justify-center shrink-0">
          <Layers size={18} />
        </div>
        <div>
          <p className="font-semibold text-sm">일괄 운송장 입력</p>
          <p className="text-xs text-indigo-200">여러 거래처 파일을 한 번에 올려서 처리 (고구마 제외)</p>
        </div>
        <svg className="ml-auto w-4 h-4 text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      <section className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700">
              <FileSpreadsheet size={20} />
            </div>
            <div>
              <p className="text-sm font-bold text-emerald-950">성주참외 알뜰과(제주다팜) 발주</p>
              <p className="mt-1 text-sm leading-6 text-emerald-800">
                쿠팡 가정용 혼합과 주문만 추출해 제주다팜 알뜰참외 발주서를 바로 생성합니다.
              </p>
            </div>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              onClick={() => navigate('/process/chamoe-mixed-order')}
              className="inline-flex items-center justify-center rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-800"
            >
              알뜰과 발주서 생성
            </button>
            <button
              onClick={() => navigate('/process/tracking-input')}
              className="inline-flex items-center justify-center rounded-lg border border-emerald-300 bg-white px-4 py-2 text-sm font-semibold text-emerald-800 transition-colors hover:bg-emerald-100"
            >
              알뜰과 송장번호 입력
            </button>
          </div>
        </div>
      </section>

      {tools.length === 0 ? (
        <div className="bg-white rounded-2xl border border-dashed border-slate-200 p-10 text-center text-slate-400 text-sm">
          표시할 도구가 없습니다.{' '}
          <Link to="/orders/settings" className="text-indigo-600 hover:underline">
            도구 설정
          </Link>
          에서 숨김/삭제한 항목을 복원할 수 있습니다.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {tools.map((tool) => (
            <ProcessCard
              key={tool.id}
              title={tool.title}
              description={tool.description}
              icon={tool.icon}
              color={tool.color}
              onClick={() => {
                if (tool.id === 'goguma-unified') {
                  navigate('/process/goguma');
                } else if (tool.id.endsWith('-unified')) {
                  const productId = tool.id.replace('-unified', '');
                  navigate(`/process/unified/${productId}`);
                } else {
                  navigate(`/process/${tool.id}`);
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default OrderTools;
