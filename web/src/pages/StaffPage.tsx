import { FormEvent, useState } from "react";

import { ALL_ROLES, api, Branch, Role, StaffRow } from "../api";
import { useAuth } from "../auth";
import { Badge, Card, ErrorBox, errText, Loading, Modal, PageHeader, useAsync } from "../ui";

export default function StaffPage() {
  const { me } = useAuth();
  const staff = useAsync(() => api.get<StaffRow[]>("/admin/staff"), []);
  const branches = useAsync(() => api.get<Branch[]>("/admin/branches"), []);
  const [msg, setMsg] = useState<string | null>(null);
  const [editing, setEditing] = useState<StaffRow | "new" | null>(null);
  const [resetting, setResetting] = useState<StaffRow | null>(null);

  const branchName = (id: number) => branches.data?.find((b) => b.branch_id === id)?.branch_name ?? `#${id}`;
  const done = (m: string) => {
    setEditing(null);
    setResetting(null);
    setMsg(m);
    void staff.reload(true);
  };

  return (
    <>
      <PageHeader title="Staff">
        <button className="primary" onClick={() => setEditing("new")}>Add staff member</button>
      </PageHeader>
      {msg && <div className="notice">{msg}</div>}
      <Card>
        {staff.loading ? <Loading /> : staff.error ? <ErrorBox message={staff.error} onRetry={() => void staff.reload()} /> : (
          <table>
            <thead><tr><th>Name</th><th>Roles</th><th>Branches</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {staff.data?.map((s) => (
                <tr key={s.staff_id}>
                  <td>{s.first_name} {s.last_name}<div className="muted small">{s.email}</div></td>
                  <td>{s.role_names.map((r) => ALL_ROLES.find((x) => x.value === r)?.label ?? r).join(", ")}</td>
                  <td>{s.role_names.includes("system_admin") ? <span className="muted">All</span> : s.branch_ids.map(branchName).join(", ") || <span className="muted">None</span>}</td>
                  <td><Badge status={s.account_status === "active" ? "available" : "unavailable"}>{s.account_status}</Badge></td>
                  <td className="actions">
                    <button onClick={() => setEditing(s)}>Edit</button>
                    <button onClick={() => setResetting(s)}>Reset password</button>
                    {s.staff_id === me?.staff_id && <span className="muted small"> (you)</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {editing && <StaffModal existing={editing === "new" ? null : editing} branches={branches.data ?? []} onClose={() => setEditing(null)} onDone={done} />}
      {resetting && <ResetModal staff={resetting} onClose={() => setResetting(null)} onDone={done} />}
    </>
  );
}

function StaffModal({ existing, branches, onClose, onDone }: { existing: StaffRow | null; branches: Branch[]; onClose: () => void; onDone: (m: string) => void }) {
  const [first, setFirst] = useState(existing?.first_name ?? "");
  const [last, setLast] = useState(existing?.last_name ?? "");
  const [email, setEmail] = useState(existing?.email ?? "");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<Role[]>(existing?.role_names ?? []);
  const [branchIds, setBranchIds] = useState<number[]>(existing?.branch_ids ?? []);
  const [active, setActive] = useState((existing?.account_status ?? "active") === "active");
  const [error, setError] = useState<string | null>(null);

  const toggle = <T,>(list: T[], v: T): T[] => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (roles.length === 0) return setError("Choose at least one role.");
    try {
      if (existing) {
        await api.patch(`/admin/staff/${existing.staff_id}`, { first_name: first, last_name: last, roles, branch_ids: branchIds, account_status: active ? "active" : "inactive" });
        onDone(`${first} ${last} updated.`);
      } else {
        await api.post("/admin/staff", { first_name: first, last_name: last, email, password, roles, branch_ids: branchIds });
        onDone(`${first} ${last} added. Give them the password you chose and ask them to keep it private.`);
      }
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <Modal title={existing ? `Edit ${existing.first_name}` : "Add staff member"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="error">{error}</div>}
        <div className="row">
          <label style={{ flex: 1 }}>First name<input value={first} onChange={(e) => setFirst(e.target.value)} required /></label>
          <label style={{ flex: 1 }}>Last name<input value={last} onChange={(e) => setLast(e.target.value)} required /></label>
        </div>
        {!existing && (
          <>
            <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
            <label>Starting password (8+ characters)<input type="text" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required /></label>
          </>
        )}
        <fieldset>
          <legend>Roles</legend>
          {ALL_ROLES.map((r) => (
            <label key={r.value} className="row"><input type="checkbox" checked={roles.includes(r.value)} onChange={() => setRoles(toggle(roles, r.value))} /> {r.label}</label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Branches {roles.includes("system_admin") && <span className="muted small">(admins can use every branch)</span>}</legend>
          {branches.map((b) => (
            <label key={b.branch_id} className="row"><input type="checkbox" checked={branchIds.includes(b.branch_id)} onChange={() => setBranchIds(toggle(branchIds, b.branch_id))} /> {b.branch_name}{b.status !== "active" ? " (inactive)" : ""}</label>
          ))}
        </fieldset>
        {existing && <label className="row"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Account is active (untick to stop them signing in)</label>}
        <button className="primary">{existing ? "Save changes" : "Add staff member"}</button>
      </form>
    </Modal>
  );
}

function ResetModal({ staff, onClose, onDone }: { staff: StaffRow; onClose: () => void; onDone: (m: string) => void }) {
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post(`/admin/staff/${staff.staff_id}/reset-password`, { new_password: pw });
      onDone(`Password changed for ${staff.first_name} ${staff.last_name}. Tell them the new password in person.`);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <Modal title={`Reset password for ${staff.first_name}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="error">{error}</div>}
        <label>New password (8+ characters)<input type="text" value={pw} onChange={(e) => setPw(e.target.value)} minLength={8} required autoFocus /></label>
        <button className="primary">Set new password</button>
      </form>
    </Modal>
  );
}
