import { useState } from "react";

import { api, AppointmentReport, BranchPerformance, pct, QueueReport, SystemSummary } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBox, Loading, PageHeader, useAsync } from "../ui";

const iso = (d: Date) => d.toLocaleDateString("en-CA");
const daysAgo = (n: number) => iso(new Date(Date.now() - n * 86400000));

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="stat">
      <span className="muted small">{label}</span>
      <strong>{value}</strong>
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}

export default function ReportsPage() {
  const { branchId, has } = useAuth();
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(iso(new Date()));
  const admin = has("system_admin");

  const appts = useAsync(() => api.get<AppointmentReport>("/reports/appointments", { branch_id: branchId ?? undefined, from, to }), [branchId, from, to]);
  const queue = useAsync(() => api.get<QueueReport>("/reports/queue", { branch_id: branchId ?? undefined, from, to }), [branchId, from, to]);
  const perf = useAsync(() => api.get<BranchPerformance[]>("/reports/branch-performance", { from, to }), [from, to]);
  const summary = useAsync(() => (admin ? api.get<SystemSummary>("/reports/system-summary") : Promise.resolve(null)), [admin]);

  const days = appts.data?.by_day ?? [];
  const max = Math.max(1, ...days.map((d) => d.total));

  return (
    <>
      <PageHeader title="Reports">
        <label className="row">From <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="row">To <input type="date" value={to} min={from} max={iso(new Date())} onChange={(e) => setTo(e.target.value)} /></label>
      </PageHeader>
      <p className="muted small">Counts and averages only. No patient details are shown here. The branch picker above filters the first two sections.</p>

      {summary.data && (
        <Card title="Whole system today">
          <div className="stats">
            <Stat label="Patients" value={summary.data.patients} />
            <Stat label="Appointments today" value={summary.data.appointments_today} />
            <Stat label="This month" value={summary.data.appointments_this_month} />
            <Stat label="Check-ins today" value={summary.data.queue_check_ins_today} />
            <Stat label="Low stock items" value={summary.data.low_stock_items} />
            <Stat label="Active staff" value={summary.data.active_staff} />
          </div>
        </Card>
      )}

      <Card title="Appointments">
        {appts.loading ? <Loading /> : appts.error ? <ErrorBox message={appts.error} onRetry={() => void appts.reload()} /> : appts.data && (
          <>
            <div className="stats">
              <Stat label="Total" value={appts.data.totals.total} />
              <Stat label="Completed" value={appts.data.totals.completed} hint={pct(appts.data.completion_rate)} />
              <Stat label="Cancelled" value={appts.data.totals.cancelled} hint={pct(appts.data.cancellation_rate)} />
              <Stat label="No-shows" value={appts.data.totals.no_show} />
              <Stat label="Still to come" value={appts.data.totals.pending} />
            </div>
            <h4>By day</h4>
            <div className="bars" role="img" aria-label="Appointments per day">
              {days.map((d) => (
                <div key={d.date} className="bar" title={`${d.date}: ${d.total} booked, ${d.completed} completed`}>
                  <div className="fill" style={{ height: `${(d.total / max) * 100}%` }} />
                  <span>{d.date.slice(8)}</span>
                </div>
              ))}
            </div>
            <h4>By service</h4>
            <table>
              <thead><tr><th>Service</th><th className="num">Total</th><th className="num">Completed</th><th className="num">Cancelled</th><th className="num">No-show</th></tr></thead>
              <tbody>
                {appts.data.by_service.map((s) => (
                  <tr key={s.id}><td>{s.name}</td><td className="num">{s.total}</td><td className="num">{s.completed}</td><td className="num">{s.cancelled}</td><td className="num">{s.no_show}</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      <Card title="Queue">
        {queue.loading ? <Loading /> : queue.error ? <ErrorBox message={queue.error} /> : queue.data && (
          <div className="stats">
            <Stat label="Patients checked in" value={queue.data.checked_in} />
            <Stat label="Average wait" value={queue.data.avg_wait_minutes === null ? "-" : `${queue.data.avg_wait_minutes} min`} />
            <Stat label="Average visit" value={queue.data.avg_service_minutes === null ? "-" : `${queue.data.avg_service_minutes} min`} />
          </div>
        )}
      </Card>

      <Card title="Branch comparison">
        {perf.loading ? <Loading /> : perf.error ? <ErrorBox message={perf.error} /> : (
          <table>
            <thead><tr><th>Branch</th><th className="num">Appointments</th><th className="num">Completed</th><th className="num">Cancelled</th><th className="num">No-show</th><th className="num">Avg wait</th></tr></thead>
            <tbody>
              {perf.data?.map((b) => (
                <tr key={b.branch_id}>
                  <td>{b.branch_name}</td>
                  <td className="num">{b.appointments.total}</td>
                  <td className="num">{pct(b.completion_rate)}</td>
                  <td className="num">{pct(b.cancellation_rate)}</td>
                  <td className="num">{pct(b.no_show_rate)}</td>
                  <td className="num">{b.avg_wait_minutes === null ? "-" : `${b.avg_wait_minutes} min`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
