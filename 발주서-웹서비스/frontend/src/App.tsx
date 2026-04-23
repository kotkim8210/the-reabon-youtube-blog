import { useState, useEffect, createContext, useContext } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Login from './pages/Login';
import AppShell from './components/AppShell';
import DashboardHome from './components/mvp/DashboardHome';
import OrderTools from './pages/OrderTools';
import ProcessPage from './pages/ProcessPage';
import GogumaAutoPage from './pages/GogumaAutoPage';
import TossAutoPage from './pages/TossAutoPage';
import GogumaUnifiedPage from './pages/GogumaUnifiedPage';
import UnifiedProcessPage from './pages/UnifiedProcessPage';
import PricingDashboard from './pages/PricingDashboard';
import PlaceholderTab from './components/mvp/PlaceholderTab';
import AdminPanel from './pages/AdminPanel';
import TenantProductConfig from './pages/TenantProductConfig';
import TenantOrderPage from './pages/TenantOrderPage';
import SignupPage from './pages/SignupPage';
import PricingPage from './pages/PricingPage';
import BillingDashboard from './pages/BillingDashboard';
import SalesDashboard from './pages/SalesDashboard';
import ToolSettings from './pages/ToolSettings';
import BatchTrackingPage from './pages/BatchTrackingPage';
import NotFound from './pages/NotFound';
import { checkAuthConfig, fetchMe, UserMe } from './api';

// Global auth state
let _authDisabled = false;
export function isAuthDisabled() { return _authDisabled; }

// User context
interface UserContextType {
  user: UserMe | null;
  setUser: (u: UserMe | null) => void;
}
const UserContext = createContext<UserContextType>({ user: null, setUser: () => {} });
export function useUser() { return useContext(UserContext); }

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  const location = useLocation();

  if (_authDisabled) {
    return <>{children}</>;
  }

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}

function App() {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<UserMe | null>(null);

  useEffect(() => {
    checkAuthConfig()
      .then((config) => {
        _authDisabled = config.auth_disabled;
      })
      .catch(() => {
        _authDisabled = false;
      })
      .finally(() => {
        // Try to fetch user info if token exists
        const token = localStorage.getItem('token');
        if (token && !_authDisabled) {
          fetchMe()
            .then(setUser)
            .catch(() => {
              localStorage.removeItem('token');
            })
            .finally(() => setReady(true));
        } else {
          setReady(true);
        }
      });
  }, []);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="animate-spin w-8 h-8 border-4 border-indigo-200 border-t-indigo-600 rounded-full" />
      </div>
    );
  }

  return (
    <UserContext.Provider value={{ user, setUser }}>
      <Routes>
        <Route
          path="/login"
          element={_authDisabled ? <Navigate to="/" replace /> : <Login />}
        />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route
          path="/"
          element={
            <PrivateRoute>
              <AppShell />
            </PrivateRoute>
          }
        >
          <Route index element={<DashboardHome />} />
          <Route path="orders" element={<OrderTools />} />
          <Route path="orders/batch-tracking" element={<BatchTrackingPage />} />
          <Route path="orders/settings" element={<ToolSettings />} />
          <Route path="process/goguma" element={<GogumaUnifiedPage />} />
          <Route path="process/unified/:productId" element={<UnifiedProcessPage />} />
          <Route path="process/goguma-auto" element={<GogumaAutoPage />} />
          <Route path="process/toss-auto" element={<TossAutoPage />} />
          <Route path="process/:toolId" element={<ProcessPage />} />
          <Route path="pricing" element={<PricingDashboard />} />
          <Route path="inventory" element={<PlaceholderTab />} />
          <Route path="cs" element={<PlaceholderTab />} />
          <Route path="ai-content" element={<PlaceholderTab />} />
          <Route path="roas" element={<PlaceholderTab />} />
          {/* Tenant routes */}
          <Route path="my/products" element={<TenantProductConfig />} />
          <Route path="my/process" element={<TenantOrderPage />} />
          <Route path="billing" element={<BillingDashboard />} />
          <Route path="sales" element={<SalesDashboard />} />
          {/* Admin route */}
          <Route path="admin" element={<AdminPanel />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </UserContext.Provider>
  );
}

export default App;
