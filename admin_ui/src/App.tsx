import { HashRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { Layout } from "./components/Layout";
import { LoginForm } from "./components/LoginForm";
import { ProtectedRoute } from "./components/ProtectedRoute";
import Dashboard from "./components/Dashboard";
import OrdersView from "./components/OrdersView";
import OrderDetail from "./components/OrderDetail";
import ReconciliationView from "./components/ReconciliationView";
import AccountsView from "./components/AccountsView";
import DecisionsView from "./components/DecisionsView";

export default function App() {
  return (
    <HashRouter>
      <AuthProvider>
        <Routes>
          {/* Login — no layout */}
          <Route path="/login" element={<LoginForm />} />

          {/* Protected routes — with sidebar layout */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="orders" element={<OrdersView />} />
            <Route path="orders/:orderId" element={<OrderDetail />} />
            <Route path="reconciliation" element={<ReconciliationView />} />
            <Route path="accounts" element={<AccountsView />} />
            <Route path="decisions" element={<DecisionsView />} />
          </Route>
        </Routes>
      </AuthProvider>
    </HashRouter>
  );
}
