import { FormEvent, useState } from "react";

import { api, Branch, BranchServiceRow, DAY_NAMES, Hours, ServiceFull } from "../api";
import { useAuth } from "../auth";
import { Badge, Card, ErrorBox, errText, Loading, Modal, PageHeader, useAsync } from "../ui";

const hhmm = (t: string) => t.slice(0, 5);

export default function BranchesPage() {
  const { branchId, branches, has, refresh } = useAuth();
  const admin = has("system_admin");
  const [msg, setMsg] = useState<string | null>(null);
  const [editing, setEditing] = useState<Branch | "new" | null>(null);
  const all = useAsync(() => (admin ? api.get<Branch[]>("/admin/branches") : Promise.resolve([] as Branch[])), [admin]);
  const current = branches.find((b) => b.branch_id === branchId);

  const saved = async (m: string) => {
    setMsg(m);
    await refresh();
    void all.reload(true);
  };

  return (
    <>
      <PageHeader title="Branches">
        {admin && <button className="primary" onClick={() => setEditing("new")}>Add branch</button>}
      </PageHeader>
      {msg && <div className="notice">{msg}</div>}

      {admin && (
        <Card title="All branches">
          {all.loading ? <Loading /> : all.error ? <ErrorBox message={all.error} /> : (
            <table>
              <thead><tr><th>Branch</th><th>Address</th><th>Phone</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {all.data?.map((b) => (
                  <tr key={b.branch_id}>
                    <td>{b.branch_name}</td>
                    <td>{b.address ?? "-"}</td>
                    <td>{b.phone ?? "-"}</td>
                    <td><Badge status={b.status === "active" ? "available" : "unavailable"}>{b.status}</Badge></td>
                    <td className="actions"><button onClick={() => setEditing(b)}>Edit</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {current ? (
        <>
          <h3 className="section">{current.branch_name}</h3>
          <p className="muted small">The settings below are for the branch chosen in the picker at the top right.</p>
          <HoursCard key={`h${current.branch_id}`} branch={current} onSaved={saved} />
          <ServicesCard key={`s${current.branch_id}`} branchId={current.branch_id} onChanged={setMsg} />
        </>
      ) : (
        <p className="muted">Pick a branch at the top right to manage its hours and services.</p>
      )}

      {editing && (
        <BranchModal
          existing={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onDone={(m) => {
            setEditing(null);
            void saved(m);
          }}
        />
      )}
    </>
  );
}

function BranchModal({ existing, onClose, onDone }: { existing: Branch | null; onClose: () => void; onDone: (m: string) => void }) {
  const [name, setName] = useState(existing?.branch_name ?? "");
  const [address, setAddress] = useState(existing?.address ?? "");
  const [phone, setPhone] = useState(existing?.phone ?? "");
  const [active, setActive] = useState((existing?.status ?? "active") === "active");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (existing) {
        await api.patch(`/branches/${existing.branch_id}`, { branch_name: name, address: address || null, phone: phone || null, status: active ? "active" : "inactive" });
      } else {
        await api.post("/branches", { branch_name: name, address: address || null, phone: phone || null });
      }
      onDone(`${name} saved.${existing ? "" : " Now set its opening hours and services, and assign staff to it."}`);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <Modal title={existing ? "Edit branch" : "Add branch"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="error">{error}</div>}
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label>Address<input value={address} onChange={(e) => setAddress(e.target.value)} /></label>
        <label>Phone<input value={phone} onChange={(e) => setPhone(e.target.value)} /></label>
        {existing && <label className="row"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Open for bookings (untick to hide it from patients)</label>}
        <button className="primary">Save</button>
      </form>
    </Modal>
  );
}

interface DayState {
  open: boolean;
  from: string;
  to: string;
}

function HoursCard({ branch, onSaved }: { branch: Branch; onSaved: (m: string) => void | Promise<void> }) {
  const [days, setDays] = useState<DayState[]>(() =>
    DAY_NAMES.map((_, i) => {
      const h = branch.hours.find((x) => x.day_of_week === i);
      return h ? { open: true, from: hhmm(h.open_time), to: hhmm(h.close_time) } : { open: false, from: "08:00", to: "17:00" };
    }),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (i: number, patch: Partial<DayState>) => setDays(days.map((d, j) => (j === i ? { ...d, ...patch } : d)));

  async function save() {
    setError(null);
    for (const [i, d] of days.entries()) {
      if (d.open && d.from >= d.to) return setError(`${DAY_NAMES[i]}: closing time must be after opening time.`);
    }
    setBusy(true);
    try {
      const body: Hours[] = days.flatMap((d, i) => (d.open ? [{ day_of_week: i, open_time: d.from, close_time: d.to }] : []));
      await api.put(`/branches/${branch.branch_id}/hours`, body);
      await onSaved("Opening hours saved. Existing time slots are not changed; generate new slots below to use the new hours.");
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Opening hours" actions={<button className="primary" onClick={() => void save()} disabled={busy}>Save hours</button>}>
      {error && <div className="error">{error}</div>}
      <table>
        <tbody>
          {days.map((d, i) => (
            <tr key={i}>
              <td style={{ width: 140 }}><label className="row"><input type="checkbox" checked={d.open} onChange={(e) => set(i, { open: e.target.checked })} /> {DAY_NAMES[i]}</label></td>
              <td>
                {d.open ? (
                  <span className="row"><input type="time" value={d.from} onChange={(e) => set(i, { from: e.target.value })} /> to <input type="time" value={d.to} onChange={(e) => set(i, { to: e.target.value })} /></span>
                ) : <span className="muted">Closed</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function ServicesCard({ branchId, onChanged }: { branchId: number; onChanged: (m: string) => void }) {
  const mine = useAsync(() => api.get<BranchServiceRow[]>(`/branches/${branchId}/services`), [branchId]);
  const catalogue = useAsync(() => api.get<ServiceFull[]>("/services"), []);
  const [pick, setPick] = useState("");
  const [slotsFor, setSlotsFor] = useState<BranchServiceRow | null>(null);

  const offeredIds = new Set((mine.data ?? []).map((s) => s.service_id));
  const addable = (catalogue.data ?? []).filter((s) => !offeredIds.has(s.service_id));

  async function run(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      onChanged(ok);
    } catch (e) {
      onChanged(errText(e));
    }
    void mine.reload(true);
  }

  return (
    <Card
      title="Services offered here"
      actions={
        <>
          <select value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Add a service…</option>
            {addable.map((s) => <option key={s.service_id} value={s.service_id}>{s.service_name}</option>)}
          </select>
          <button disabled={!pick} onClick={() => void run(() => api.put(`/branches/${branchId}/services/${pick}`, { availability_status: "available" }), "Service added to this branch.").then(() => setPick(""))}>Add</button>
        </>
      }
    >
      {mine.loading ? <Loading /> : mine.error ? <ErrorBox message={mine.error} /> : (mine.data ?? []).length === 0 ? <p className="muted">No services yet. Add one above.</p> : (
        <table>
          <thead><tr><th>Service</th><th className="num">Minutes</th><th>Bookable</th><th></th></tr></thead>
          <tbody>
            {mine.data?.map((s) => (
              <tr key={s.service_id}>
                <td>{s.service_name}</td>
                <td className="num">{s.estimated_duration_min}</td>
                <td><Badge status={s.availability_status}>{s.availability_status}</Badge></td>
                <td className="actions">
                  <button onClick={() => setSlotsFor(s)}>Create time slots</button>
                  <button onClick={() => void run(() => api.put(`/branches/${branchId}/services/${s.service_id}`, { availability_status: s.availability_status === "available" ? "unavailable" : "available" }), `${s.service_name} updated.`)}>
                    {s.availability_status === "available" ? "Pause" : "Resume"}
                  </button>
                  <button className="danger" onClick={() => window.confirm(`Stop offering ${s.service_name} at this branch?`) && void run(() => api.del(`/branches/${branchId}/services/${s.service_id}`), `${s.service_name} removed from this branch.`)}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {slotsFor && <SlotsModal branchId={branchId} service={slotsFor} onClose={() => setSlotsFor(null)} onDone={(m) => { setSlotsFor(null); onChanged(m); }} />}
    </Card>
  );
}

function SlotsModal({ branchId, service, onClose, onDone }: { branchId: number; service: BranchServiceRow; onClose: () => void; onDone: (m: string) => void }) {
  const today = new Date().toLocaleDateString("en-CA");
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState(new Date(Date.now() + 13 * 86400000).toLocaleDateString("en-CA"));
  const [capacity, setCapacity] = useState("1");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api.post<Record<string, unknown>>(`/branches/${branchId}/slots/generate`, { service_id: service.service_id, from_date: from, to_date: to, capacity: Number(capacity) });
      const made = r.created ?? r.slots_created ?? r.count;
      onDone(typeof made === "number" ? `${made} time slots created for ${service.service_name}.` : `Time slots created for ${service.service_name}.`);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <Modal title={`Create time slots: ${service.service_name}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="error">{error}</div>}
        <p className="muted small">Slots follow the branch's opening hours and the service's length. Days that already have slots are left alone.</p>
        <div className="row">
          <label style={{ flex: 1 }}>From<input type="date" value={from} min={today} onChange={(e) => setFrom(e.target.value)} required /></label>
          <label style={{ flex: 1 }}>To<input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} required /></label>
        </div>
        <label>Patients per slot<input type="number" min={1} max={50} value={capacity} onChange={(e) => setCapacity(e.target.value)} required /></label>
        <button className="primary">Create slots</button>
      </form>
    </Modal>
  );
}
