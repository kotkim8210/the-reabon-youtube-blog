import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Bell,
  CreditCard,
  LayoutDashboard,
  LogOut,
  Menu,
  RefreshCw,
  Search,
  Settings,
  Shield,
  ShoppingCart,
  SlidersHorizontal,
  Sparkles,
  User,
  X,
} from 'lucide-react';

import { fetchSupplierPriceAlerts, refreshDashboardData, type SupplierPriceAlertRun } from '../api';
import { isAuthDisabled, useUser } from '../App';
import AdminModal from './AdminModal';
import SidebarItem from './mvp/SidebarItem';

const adminNavItems = [
  { icon: LayoutDashboard, label: '자동화 대시보드', path: '/' },
  { icon: ShoppingCart, label: '발주 도구', path: '/orders' },
  { icon: CreditCard, label: '구독 & 사용량', path: '/billing' },
];

const tenantNavItems = [
  { icon: LayoutDashboard, label: '자동화 대시보드', path: '/' },
  { icon: ShoppingCart, label: '내 발주 자동화', path: '/my/process' },
  { icon: Settings, label: '상품/양식 설정', path: '/my/products' },
  { icon: CreditCard, label: '구독 & 사용량', path: '/billing' },
];

const aiItems = [
  { icon: Shield, label: '마진 방어', path: '/#margin-defense' },
  { icon: Sparkles, label: 'AI 상세페이지', path: '/ai-content' },
];

export default function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useUser();
  const isAdmin = user?.role === 'admin';
  const navItems = isAdmin ? adminNavItems : tenantNavItems;
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [supplierAlerts, setSupplierAlerts] = useState<SupplierPriceAlertRun[]>([]);
  const [supplierAlertCount, setSupplierAlertCount] = useState(0);

  const loadSupplierAlerts = async () => {
    if (!isAdmin) return;
    try {
      const data = await fetchSupplierPriceAlerts();
      setSupplierAlerts(data.alerts);
      setSupplierAlertCount(data.active_count);
    } catch {
      setSupplierAlerts([]);
      setSupplierAlertCount(0);
    }
  };

  const handleRefresh = async () => {
    setLoading(true);
    try {
      await refreshDashboardData();
      await loadSupplierAlerts();
    } catch {
      // noop
    } finally {
      setTimeout(() => setLoading(false), 500);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/';
    }
    return location.pathname.startsWith(path);
  };

  const handleNav = (path: string) => {
    navigate(path);
    setSidebarOpen(false);

    if (path === '/#margin-defense') {
      window.setTimeout(() => {
        document.getElementById('margin-defense')?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      }, 120);
    }
  };

  useEffect(() => {
    if (!isAdmin) return;
    loadSupplierAlerts();
    const interval = window.setInterval(loadSupplierAlerts, 5 * 60 * 1000);
    return () => window.clearInterval(interval);
  }, [isAdmin]);

  const activeSupplierAlerts = supplierAlerts
    .filter((alert) => alert.status !== 'ok' || Number(alert.changed_items || 0) > 0)
    .sort((left, right) => {
      const leftCritical = left.status !== 'ok' ? 1 : 0;
      const rightCritical = right.status !== 'ok' ? 1 : 0;
      if (leftCritical !== rightCritical) return rightCritical - leftCritical;
      return Number(right.changed_items || 0) - Number(left.changed_items || 0);
    });

  return (
    <div className="flex min-h-screen overflow-hidden bg-[#f7f4ee] text-slate-900">
      {sidebarOpen && (
        <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 transform overflow-y-auto border-r border-slate-200 bg-white/95 p-6 transition-transform duration-200 md:static md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <button
          onClick={() => setSidebarOpen(false)}
          className="absolute right-4 top-4 text-slate-400 hover:text-slate-600 md:hidden"
        >
          <X size={20} />
        </button>

        <div className="mb-10 flex items-center space-x-3 px-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-400 text-slate-900 shadow-lg shadow-amber-200">
            <Shield size={22} />
          </div>
          <div>
            <p className="text-lg font-black tracking-tight text-slate-900">매출가드</p>
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-amber-700">Ops System</p>
          </div>
        </div>

        <nav className="flex-1 space-y-2">
          {navItems.map((item) => (
            <SidebarItem
              key={item.path}
              icon={item.icon}
              label={item.label}
              active={isActive(item.path)}
              onClick={() => handleNav(item.path)}
            />
          ))}

          {isAdmin && (
            <>
              <div className="pb-4 pt-8">
                <span className="px-4 text-[10px] font-black uppercase tracking-[0.2em] text-slate-400">
                  Ops AI
                </span>
              </div>

              {aiItems.map((item) => (
                <SidebarItem
                  key={item.path}
                  icon={item.icon}
                  label={item.label}
                  active={isActive(item.path)}
                  onClick={() => handleNav(item.path)}
                />
              ))}

              <div className="pb-4 pt-8">
                <span className="px-4 text-[10px] font-black uppercase tracking-[0.2em] text-slate-400">
                  Admin
                </span>
              </div>
              <SidebarItem
                icon={User}
                label="사용자 관리"
                active={isActive('/admin')}
                onClick={() => handleNav('/admin')}
              />
              <SidebarItem
                icon={SlidersHorizontal}
                label="도구 설정"
                active={isActive('/orders/settings')}
                onClick={() => handleNav('/orders/settings')}
              />
            </>
          )}
        </nav>

        <div className="mt-auto space-y-3 border-t border-slate-100 pt-6">
          <div className="flex items-center space-x-3 rounded-2xl bg-slate-100 p-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white text-slate-700">
              <User size={20} />
            </div>
            <div>
              <p className="text-xs font-black text-slate-900">{user?.username || '사용자'}</p>
              <p className="text-[10px] font-bold text-slate-500">{isAdmin ? 'Admin' : 'Operator'}</p>
            </div>
          </div>

          {!isAuthDisabled() && (
            <button
              onClick={handleLogout}
              className="flex w-full items-center space-x-3 rounded-xl px-4 py-3 text-slate-500 transition-all hover:bg-red-50 hover:text-red-600"
            >
              <LogOut size={20} />
              <span className="font-medium">로그아웃</span>
            </button>
          )}
        </div>
      </aside>

      <main className="flex h-screen flex-1 flex-col overflow-hidden">
        <header className="z-20 flex h-16 flex-shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-4 backdrop-blur md:h-20 md:px-8">
          <div className="flex items-center gap-4">
            <button onClick={() => setSidebarOpen(true)} className="p-2 text-slate-400 hover:text-amber-600 md:hidden">
              <Menu size={24} />
            </button>
            <div className="hidden items-center rounded-2xl bg-white px-4 py-2 shadow-sm sm:flex sm:w-80 lg:w-96">
              <Search size={18} className="mr-2 text-slate-400" />
              <input
                type="text"
                placeholder="옵션명, 주문번호, 배치명을 빠르게 찾아보세요"
                className="w-full border-none bg-transparent text-sm outline-none"
              />
            </div>
          </div>

          <div className="flex items-center space-x-2 md:space-x-4">
            <button
              onClick={handleRefresh}
              className={`p-2 text-slate-400 transition-all hover:text-amber-600 ${loading ? 'animate-spin' : ''}`}
            >
              <RefreshCw size={20} />
            </button>
            <div className="relative">
              <button
                onClick={() => setAlertsOpen((current) => !current)}
                className="p-2 text-slate-400 transition-all hover:text-amber-600"
                title="마진방어 알림"
              >
                <Bell size={20} />
              </button>
              {supplierAlertCount > 0 && (
                <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-black text-white ring-2 ring-white">
                  {supplierAlertCount > 9 ? '9+' : supplierAlertCount}
                </span>
              )}
              {alertsOpen && (
                <div className="absolute right-0 top-11 z-50 w-[340px] overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl shadow-slate-900/15">
                  <div className="border-b border-slate-100 bg-slate-50 px-5 py-4">
                    <p className="text-xs font-black uppercase tracking-[0.18em] text-emerald-600">Margin Defense</p>
                    <h3 className="mt-1 text-base font-black text-slate-900">마진방어 공급가 알림</h3>
                    <p className="mt-1 text-xs text-slate-500">매일 오전 10시 자동으로 어드민/스프레드시트 단가를 확인합니다.</p>
                  </div>
                  <div className="max-h-96 overflow-y-auto p-3">
                    {activeSupplierAlerts.length ? (
                      activeSupplierAlerts.slice(0, 8).map((alert) => (
                        <button
                          key={`${alert.monitor_key}-${alert.id}`}
                          onClick={() => {
                            setAlertsOpen(false);
                            handleNav('/#margin-defense');
                          }}
                          className="mb-2 w-full rounded-2xl border border-slate-100 bg-white p-3 text-left transition hover:border-emerald-200 hover:bg-emerald-50/50"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-black text-slate-900">
                                {alert.product_name || alert.monitor_key}
                              </p>
                              <p className="mt-1 text-xs text-slate-500">
                                {alert.supplier_name || '거래처'} · {new Date(alert.checked_at).toLocaleString('ko-KR')}
                              </p>
                            </div>
                            <span className={`rounded-full px-2 py-1 text-[11px] font-black ${
                              alert.status !== 'ok'
                                ? 'bg-rose-100 text-rose-700'
                                : 'bg-amber-100 text-amber-700'
                            }`}>
                              {alert.status !== 'ok' ? '오류' : `${alert.changed_items}건 변동`}
                            </span>
                          </div>
                          {alert.status !== 'ok' ? (
                            <p className="mt-2 line-clamp-2 text-xs text-rose-600">{alert.error_message}</p>
                          ) : (
                            <p className="mt-2 text-xs text-slate-600">
                              상승 {alert.blue_count}건 · 하락 {alert.red_count}건 · 동일 {alert.same_count}건
                            </p>
                          )}
                        </button>
                      ))
                    ) : (
                      <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-5 text-sm text-slate-500">
                        아직 확인할 공급가 변동 알림이 없습니다.
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
            <button onClick={() => setAdminOpen(true)} className="p-2 text-slate-400 transition-all hover:text-amber-600">
              <Settings size={20} />
            </button>
            <div className="hidden items-center md:flex">
              <div className="mx-2 h-8 w-px bg-slate-200" />
              <span className="text-sm font-bold text-slate-700">{user?.username || '게스트'}</span>
            </div>
          </div>
        </header>

        <div className="custom-scrollbar flex-1 overflow-y-auto p-4 pb-20 md:p-8">
          <Outlet />
        </div>
      </main>

      <AdminModal isOpen={adminOpen} onClose={() => setAdminOpen(false)} />
    </div>
  );
}
