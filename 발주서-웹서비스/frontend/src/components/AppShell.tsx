import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  BarChart3,
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
  TrendingUp,
  User,
  X,
} from 'lucide-react';

import { refreshDashboardData } from '../api';
import { isAuthDisabled, useUser } from '../App';
import AdminModal from './AdminModal';
import SidebarItem from './mvp/SidebarItem';

const adminNavItems = [
  { icon: LayoutDashboard, label: '자동화 대시보드', path: '/' },
  { icon: ShoppingCart, label: '발주 도구', path: '/orders' },
  { icon: TrendingUp, label: '판매 추적', path: '/sales' },
  { icon: CreditCard, label: '구독 & 사용량', path: '/billing' },
];

const tenantNavItems = [
  { icon: LayoutDashboard, label: '자동화 대시보드', path: '/' },
  { icon: ShoppingCart, label: '기존 발주 처리', path: '/my/process' },
  { icon: Settings, label: '상품 설정', path: '/my/products' },
  { icon: TrendingUp, label: '판매 대시보드', path: '/sales' },
  { icon: CreditCard, label: '구독 & 사용량', path: '/billing' },
];

const aiItems = [
  { icon: Shield, label: '마진 방어', path: '/pricing' },
  { icon: Sparkles, label: 'AI 상세페이지', path: '/ai-content' },
  { icon: BarChart3, label: 'ROAS 분석', path: '/roas' },
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

  const handleRefresh = async () => {
    setLoading(true);
    try {
      await refreshDashboardData();
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
  };

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
              <button className="p-2 text-slate-400 transition-all hover:text-amber-600">
                <Bell size={20} />
              </button>
              <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-rose-500 ring-2 ring-white" />
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
