import { NavLink, Outlet } from "react-router-dom";

import type { NavItem } from "./App";
import { useAuth } from "./auth";

const ROLE_LABEL: Record<string, string> = {
  receptionist: "Receptionist",
  nurse: "Nurse",
  clinic_manager: "Clinic manager",
  inventory_manager: "Inventory manager",
  system_admin: "System admin",
};

export default function Layout({ items }: { items: NavItem[] }) {
  const { me, branches, branchId, setBranchId, logout } = useAuth();
  return (
    <div className="shell">
      <aside>
        <h1>ClinicConnect</h1>
        <nav>
          {items.map((n) => (
            <NavLink key={n.path} to={`/${n.path}`} className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="who">
          <strong>{me?.first_name} {me?.last_name}</strong>
          <span>{me?.role_names.map((r) => ROLE_LABEL[r] ?? r).join(", ")}</span>
          <button className="link" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main>
        <div className="topbar">
          <label>
            Branch{" "}
            <select value={branchId ?? ""} onChange={(e) => setBranchId(Number(e.target.value))} disabled={branches.length < 2}>
              {branches.map((b) => (
                <option key={b.branch_id} value={b.branch_id}>{b.branch_name}</option>
              ))}
            </select>
          </label>
        </div>
        {branchId === null ? <p className="error">You are not assigned to any branch yet. Ask a system admin to assign you.</p> : <Outlet />}
      </main>
    </div>
  );
}
