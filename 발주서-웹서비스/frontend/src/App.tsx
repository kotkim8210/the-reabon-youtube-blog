import { createContext, useContext, useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { checkAuthConfig, fetchMe, UserMe } from './api';
import AppShell from './components/AppShell';
import PlaceholderTab from './components/mvp/PlaceholderTab';
import AdminPanel from './pages/AdminPanel';
import BatchTrackingPage from './pages/BatchTrackingPage';
import BillingDashboard from './pages/BillingDashboard';
import CsRefundTemplatePage from './pages/CsRefundTemplatePage';
import GogumaAutoPage from './pages/GogumaAutoPage';
import GogumaUnifiedPage from './pages/GogumaUnifiedPage';
import Login from './pages/Login';
import NotFound from './pages/NotFound';
import OrderAutomationDashboard from './pages/OrderAutomationDashboard';
import OrderTools from './pages/OrderTools';
import PricingDashboard from './pages/PricingDashboard';
import PricingPage from './pages/PricingPage';
import ProcessPage from './pages/ProcessPage';
import SignupPage from './pages/SignupPage';
import TenantOrderPage from './pages/TenantOrderPage';
import TenantProductConfig from './pages/TenantProductConfig';
import ToolSettings from './pages/ToolSettings';
import TossAutoPage from './pages/TossAutoPage';
import UnifiedProcessPage from './pages/UnifiedProcessPage';

let authDisabled = false;
export function isAuthDisabled() {
  return authDisabled;
}

interface UserContextType {
  user: UserMe | null;
  setUser: (nextUser: UserMe | null) => void;
}

const UserContext = createContext<UserContextType>({
  user: null,
  setUser: () => undefined,
});

export function useUser() {
  return useContext(UserContext);
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  const location = useLocation();

  if (authDisabled) {
    return <>{children}</>;
  }

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token');
  const location = useLocation();
  const { user } = useUser();

  if (authDisabled) {
    return <>{children}</>;
  }

  if (!token) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (user?.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<UserMe | null>(null);

  useEffect(() => {
    checkAuthConfig()
      .then((config) => {
        authDisabled = config.auth_disabled;
      })
      .catch(() => {
        authDisabled = false;
      })
      .finally(() => {
        const token = localStorage.getItem('token');
        if (token && !authDisabled) {
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
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-amber-200 border-t-amber-500" />
      </div>
    );
  }

  return (
    <UserContext.Provider value={{ user, setUser }}>
      <Routes>
        <Route path="/login" element={authDisabled ? <Navigate to="/" replace /> : <Login />} />
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
          <Route index element={<OrderAutomationDashboard />} />
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
          <Route path="cs" element={<CsRefundTemplatePage />} />
          <Route path="ai-content" element={<PlaceholderTab />} />
          <Route path="my/products" element={<TenantProductConfig />} />
          <Route path="my/process" element={<TenantOrderPage />} />
          <Route path="billing" element={<BillingDashboard />} />
          <Route
            path="admin"
            element={
              <AdminRoute>
                <AdminPanel />
              </AdminRoute>
            }
          />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </UserContext.Provider>
  );
}
