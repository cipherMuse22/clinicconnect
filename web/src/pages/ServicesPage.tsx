import { FormEvent, useState } from "react";

import { api, ServiceFull } from "../api";
import { Badge, Card, ErrorBox, errText, Loading, Modal, PageHeader, useAsync } from "../ui";

export default function ServicesPage() {
  const list = useAsync(() => api.get<ServiceFull[]>("/admin/services"), []);
  const [editing, setEditing] = useState<ServiceFull | "new" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  return (
    <>
      <PageHeader title="Services">
        <button className="primary" onClick={() => setEditing("new")}>Add service</button>
      </PageHeader>
      <p className="muted small">This is the list of everything the clinic group offers. Each branch chooses which of these it provides under Branches.</p>
      {msg && <div className="notice">{msg}</div>}
      <Card>
        {list.loading ? <Loading /> : list.error ? <ErrorBox message={list.error} onRetry={() => void list.reload()} /> : (
          <table>
            <thead><tr><th>Service</th><th className="num">Minutes</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {list.data?.map((s) => (
                <tr key={s.service_id}>
                  <td>{s.service_name}<div className="muted small">{s.description}</div></td>
                  <td className="num">{s.estimated_duration_min}</td>
                  <td><Badge status={s.status === "active" ? "available" : "unavailable"}>{s.status}</Badge></td>
                  <td className="actions"><button onClick={() => setEditing(s)}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {editing && (
        <ServiceModal
          existing={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onDone={(m) => {
            setEditing(null);
            setMsg(m);
            void list.reload(true);
          }}
        />
      )}
    </>
  );
}

function ServiceModal({ existing, onClose, onDone }: { existing: ServiceFull | null; onClose: () => void; onDone: (m: string) => void }) {
  const [name, setName] = useState(existing?.service_name ?? "");
  const [desc, setDesc] = useState(existing?.description ?? "");
  const [mins, setMins] = useState(String(existing?.estimated_duration_min ?? 15));
  const [active, setActive] = useState((existing?.status ?? "active") === "active");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (existing) {
        await api.patch(`/services/${existing.service_id}`, { service_name: name, description: desc || null, estimated_duration_min: Number(mins), status: active ? "active" : "inactive" });
      } else {
        await api.post("/services", { service_name: name, description: desc || null, estimated_duration_min: Number(mins) });
      }
      onDone(`${name} saved.`);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <Modal title={existing ? "Edit service" : "Add service"} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        {error && <div className="error">{error}</div>}
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /></label>
        <label>Description<input value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
        <label>How long does it take (minutes)?<input type="number" min={1} max={480} value={mins} onChange={(e) => setMins(e.target.value)} required /></label>
        {existing && <label className="row"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Offered (untick to hide it everywhere)</label>}
        <button className="primary">Save</button>
      </form>
    </Modal>
  );
}
