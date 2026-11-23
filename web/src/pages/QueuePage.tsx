import { FormEvent, useState } from "react";

import { api, QueueRow, shortTime, todayIso } from "../api";
import { useAuth } from "../auth";
import { Badge, Card, ErrorBox, errText, Loading, Modal, PageHeader, useAsync } from "../ui";

export default function QueuePage() {
  const { branchId, has } = useAuth();
  const [msg, setMsg] = useState<string | null>(null);
  const [showQr, setShowQr] = useState(false);
  const [ref, setRef] = useState("");
  const isNurse = has("nurse");
  const isFront = has("receptionist", "clinic_manager", "system_admin");

  // Refreshes by itself every 10 seconds so the room stays up to date.
  const q = useAsync(() => api.get<QueueRow[]>(`/branches/${branchId}/queue`, { date: todayIso() }), [branchId], 10000);

  async function act(fn: () => Promise<unknown>, ok?: string) {
    setMsg(null);
    try {
      await fn();
      if (ok) setMsg(ok);
    } catch (e) {
      setMsg(errText(e));
    }
    void q.reload(true);
  }

  async function checkIn(e: FormEvent) {
    e.preventDefault();
    await act(() => api.post(`/branches/${branchId}/check-in`, { appointment_reference: ref.trim() }), "Patient checked in.");
    setRef("");
  }

  const rows = q.data ?? [];
  const waiting = rows.filter((r) => r.queue_status === "waiting").length;

  return (
    <>
      <PageHeader title="Today's queue">
        {isNurse && (
          <button className="primary" onClick={() => act(() => api.post(`/branches/${branchId}/queue/call-next`), "Next patient called.")} disabled={waiting === 0}>
            Call next ({waiting} waiting)
          </button>
        )}
        {isFront && <button onClick={() => setShowQr(true)}>Show clinic QR</button>}
      </PageHeader>

      {msg && <div className="notice">{msg}</div>}

      {isFront && (
        <Card title="Check in a patient at the desk">
          <form className="row" onSubmit={checkIn}>
            <input placeholder="Appointment reference, e.g. APT-5SCT9FGU" value={ref} onChange={(e) => setRef(e.target.value)} required style={{ minWidth: 300 }} />
            <button className="primary">Check in</button>
          </form>
        </Card>
      )}

      <Card>
        {q.loading && !q.data ? (
          <Loading />
        ) : q.error && !q.data ? (
          <ErrorBox message={q.error} onRetry={() => void q.reload()} />
        ) : rows.length === 0 ? (
          <p className="muted">Nobody has checked in yet today.</p>
        ) : (
          <table>
            <thead>
              <tr><th>#</th><th>Patient</th><th>Service</th><th>Booked</th><th>Arrived</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.queue_id}>
                  <td><strong>{r.queue_number}</strong></td>
                  <td>{r.patient_name}<div className="muted small">{r.appointment_reference}</div></td>
                  <td>{r.service_name}</td>
                  <td>{shortTime(r.appointment_time)}</td>
                  <td>{new Date(r.check_in_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                  <td><Badge status={r.queue_status} /></td>
                  <td className="actions">
                    {isNurse && r.queue_status === "called" && <button onClick={() => act(() => api.patch(`/queue/${r.queue_id}/status`, { status: "in_service" }))}>Start visit</button>}
                    {isNurse && r.queue_status === "in_service" && <button className="primary" onClick={() => act(() => api.post(`/queue/${r.queue_id}/complete`), "Visit completed.")}>Complete</button>}
                    {(r.queue_status === "waiting" || r.queue_status === "called") && isFront && (
                      <button className="danger" onClick={() => window.confirm(`Skip ${r.patient_name}?`) && act(() => api.patch(`/queue/${r.queue_id}/status`, { status: "skipped" }))}>Skip</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {showQr && <QrModal branchId={branchId!} onClose={() => setShowQr(false)} />}
    </>
  );
}

function QrModal({ branchId, onClose }: { branchId: number; onClose: () => void }) {
  const qr = useAsync(() => api.blobUrl(`/branches/${branchId}/check-in-qr.png`), [branchId]);
  return (
    <Modal title="Scan to check in" onClose={onClose}>
      {qr.loading ? <Loading /> : qr.error ? <ErrorBox message={qr.error} /> : <img src={qr.data!} alt="Clinic check-in QR code" style={{ width: 320, maxWidth: "100%" }} />}
      <p className="muted small">Patients scan this in the ClinicConnect app. The code changes every day, so show it from here instead of printing it.</p>
    </Modal>
  );
}
