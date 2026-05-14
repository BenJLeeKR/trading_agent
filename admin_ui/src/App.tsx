import { HashRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Layout } from "./components/Layout";
import { LoginForm } from "./components/LoginForm";
import { ProtectedRoute } from "./components/ProtectedRoute";
import Dashboard from "./components/Dashboard";
import OrdersView from "./components/OrdersView";
import OrderDetail from "./components/OrderDetail";
import ReconciliationView from "./components/ReconciliationView";
import AccountsView from "./components/AccountsView";
import DecisionsView from "./components/DecisionsView";
import AgentRunsView from "./components/AgentRunsView";
import OperationsDashboardView from "./components/OperationsDashboardView";
import OperationsAlertsView from "./components/OperationsAlertsView";
import OrderTrackingView from "./components/OrderTrackingView";

/** Redirect to "/" if already authenticated (reverse of ProtectedRoute). */
function PublicRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <HashRouter>
      <AuthProvider>
        <Routes>
          {/* Login — no layout; redirect to dashboard if already authenticated */}
          <Route
            path="/login"
            element={
              <PublicRoute>
                <LoginForm />
              </PublicRoute>
            }
          />

          {/* Protected routes — with sidebar layout */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<OperationsDashboardView />} />
            <Route path="overview" element={<Dashboard />} />
            <Route path="orders" element={<OrdersView />} />
            <Route path="orders/:orderId" element={<OrderDetail />} />
            <Route path="reconciliation" element={<ReconciliationView />} />
            <Route path="accounts" element={<AccountsView />} />
            <Route path="decisions" element={<DecisionsView />} />
            <Route path="agent-runs" element={<AgentRunsView />} />
            <Route path="operations" element={<OperationsDashboardView />} />
            <Route path="operations/alerts" element={<OperationsAlertsView />} />
            <Route path="operations/orders" element={<OrderTrackingView />} />
          </Route>
        </Routes>
      </AuthProvider>
    </HashRouter>
  );
}
