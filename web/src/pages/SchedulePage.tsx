import { useState } from "react";

import { api, BranchService, PatientHit, shortTime, Slot, StaffAppointment, todayIso } from "../api";
import { useAuth } from "../auth";
import { Badge, Card, ErrorBox, errText, Loading, Modal, PageHeader, useAsync } from "../ui";

export default function SchedulePage() {
  const { branchId, has } = useAuth();
  const [date, setDate] = useState(todayIso());
  const [msg, setMsg] = useState<string | null>(null);
  const [booking, setBooking] = useState(false);
  const canBook = has("receptionist", "clinic_manager", "system_admin");

  const list = useAsync(() => api.get<StaffAppointment[]>(`/branches/${branchId}/appointments`, { date }), [branchId, date]);

  async function cancel(a: StaffAppointment) {
    if (!window.confirm(`Cancel ${a.patient_name}'s ${a.service_name} at ${shortTime(a.start_time)}?`)) return;
    try {
      await api.post(`/appointments/${a.appointment_id}/cancel`);
      setMsg("Appointment cancelled.");
    } catch (e) {
      setMsg(errText(e));
    }
    void list.reload(true);
  }

  const rows = list.data ?? [];
  return (
    <>
      <PageHeader title="Schedule">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        {canBook && <button className="primary" onClick={() => setBooking(true)}>Book for a patient</button>}
      </PageHeader>
      {msg && <div className="notice">{msg}</div>}
      <Card>
        {list.loading ? (
          <Loading />
        ) : list.error ? (
          <ErrorBox message={list.error} onRetry={() => void list.reload()} />
        ) : rows.length === 0 ? (
          <p className="muted">No appointments on this day.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Time</th><th>Patient</th><th>Service</th><th>Reference</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.appointment_id}>
                  <td>{shortTime(a.start_time)}-{shortTime(a.end_time)}</td>
                  <td>{a.patient_name}<div className="muted small">{a.patient_phone}</div></td>
                  <td>{a.service_name}</td>
                  <td>{a.appointment_reference}</td>
                  <td><Badge status={a.status} /></td>
                  <td className="actions">
                    {canBook && a.status === "booked" && <button className="danger" onClick={() => void cancel(a)}>Cancel</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {booking && (
        <BookModal
          branchId={branchId!}
          onClose={() => setBooking(false)}
          onBooked={(m) => {
            setBooking(false);
            setMsg(m);
            void list.reload(true);
          }}
        />
      )}
    </>
  );
}

function BookModal({ branchId, onClose, onBooked }: { branchId: number; onClose: () => void; onBooked: (msg: string) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<PatientHit[] | null>(null);
  const [patient, setPatient] = useState<PatientHit | null>(null);
  const [serviceId, setServiceId] = useState<number | null>(null);
  const [date, setDate] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);

  const services = useAsync(() => api.get<BranchService[]>(`/branches/${branchId}/services`), [branchId]);
  const slots = useAsync(
    () => (serviceId ? api.get<Slot[]>(`/branches/${branchId}/services/${serviceId}/slots`, { date }) : Promise.resolve([] as Slot[])),
    [branchId, serviceId, date],
  );

  async function search() {
    setError(null);
    try {
      setHits(await api.get<PatientHit[]>("/patients/search", { q: q.trim() }));
    } catch (e) {
      setError(errText(e));
    }
  }

  async function book(s: Slot) {
    setError(null);
    try {
      const r = await api.post<{ appointment_reference: string }>("/appointments", { slot_id: s.slot_id, patient_id: patient!.patient_id });
      onBooked(`Booked ${patient!.first_name} ${patient!.last_name} for ${shortTime(s.start_time)} (${r.appointment_reference}).`);
    } catch (e) {
      setError(errText(e));
      void slots.reload(true);
    }
  }

  return (
    <Modal title="Book for a patient" onClose={onClose}>
      {error && <div className="error">{error}</div>}
      {!patient ? (
        <>
          <div className="row">
            <input placeholder="Name, phone or membership no. (min 3 letters)" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void search()} style={{ flex: 1 }} />
            <button onClick={() => void search()} disabled={q.trim().length < 3}>Search</button>
          </div>
          {hits && hits.length === 0 && <p className="muted">No patients found.</p>}
          <ul className="list">
            {hits?.map((h) => (
              <li key={h.patient_id}>
                <button className="link" onClick={() => setPatient(h)}>{h.first_name} {h.last_name}</button>
                <span className="muted small"> {h.phone} {h.membership_number ?? ""}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <p>Patient: <strong>{patient.first_name} {patient.last_name}</strong> <button className="link" onClick={() => setPatient(null)}>change</button></p>
          <div className="row">
            <select value={serviceId ?? ""} onChange={(e) => setServiceId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Choose a service…</option>
              {services.data?.map((s) => (
                <option key={s.service_id} value={s.service_id} disabled={!s.available || !s.in_stock}>
                  {s.service_name}{!s.available ? " (unavailable)" : !s.in_stock ? " (out of stock)" : ""}
                </option>
              ))}
            </select>
            <input type="date" value={date} min={todayIso()} onChange={(e) => setDate(e.target.value)} />
          </div>
          {serviceId && (slots.loading ? <Loading /> : (
            <div className="chips">
              {(slots.data ?? []).length === 0 && <p className="muted">No times on this day.</p>}
              {slots.data?.map((s) => (
                <button key={s.slot_id} disabled={!s.available} onClick={() => void book(s)}>{shortTime(s.start_time)}{s.available ? "" : " full"}</button>
              ))}
            </div>
          ))}
        </>
      )}
    </Modal>
  );
}
