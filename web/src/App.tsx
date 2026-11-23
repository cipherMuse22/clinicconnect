import { Navigate, Route, Routes } from "react-router-dom";

import { Role } from "./api";
import { useAuth } from "./auth";
import Layout from "./Layout";
import AuditPage from "./pages/AuditPage";
import InventoryPage from "./pages/InventoryPage";
import LoginPage from "./pages/LoginPage";
import QueuePage from "./pages/QueuePage";
import ReportsPage from "./pages/ReportsPage";
import SchedulePage from "./pages/SchedulePage";

export interface NavItem {
  path: string;
  label: string;
  roles: Role[];
  element: JSX.Element;
}

export const NAV: NavItem[] = [
  { path: "queue", label: "Queue", roles: ["receptionist", "nurse", "clinic_manager", "system_admin"], element: <QueuePage /> },
  { path: "schedule", label: "Schedule", roles: ["receptionist", "nurse", "clinic_manager", "system_admin"], element: <SchedulePage /> },
  { path: "inventory", label: "Inventory", roles: ["inventory_manager", "clinic_manager", "nurse", "system_admin"], element: <InventoryPage /> },
  { path: "reports", label: "Reports", roles: ["clinic_manager", "system_admin"], element: <ReportsPage /> },
  { path: "audit", label: "Audit log", roles: ["system_admin"], element: <AuditPage /> },
];

export default function App() {
  const { me, loading, has } = useAuth();
  if (loading) return <p className="muted center">Loading…</p>;
  if (!me) return <LoginPage />;
  const allowed = NAV.filter((n) => has(...n.roles));
  return (
    <Routes>
      <Route element={<Layout items={allowed} />}>
        {allowed.map((n) => (
          <Route key={n.path} path={n.path} element={n.element} />
        ))}
        <Route path="*" element={<Navigate to={allowed[0]?.path ?? "/"} replace />} />
      </Route>
    </Routes>
  );
}
