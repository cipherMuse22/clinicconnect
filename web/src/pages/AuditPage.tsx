import { Fragment, useState } from "react";

import { api, AuditPage as AuditData } from "../api";
import { Card, ErrorBox, Loading, PageHeader, useAsync } from "../ui";

const PAGE = 25;

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);

  const log = useAsync(() => api.get<AuditData>("/admin/audit-logs", { action: action.trim() || undefined, limit: PAGE, offset }), [action, offset]);
  const total = log.data?.total ?? 0;

  return (
    <>
      <PageHeader title="Audit log">
        <input placeholder="Filter by action, e.g. staff or appointment" value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }} style={{ minWidth: 280 }} />
      </PageHeader>
      <Card>
        {log.loading && !log.data ? <Loading /> : log.error ? <ErrorBox message={log.error} onRetry={() => void log.reload()} /> : (
          <>
            <table>
              <thead><tr><th>When</th><th>Who</th><th>Action</th><th>What</th><th></th></tr></thead>
              <tbody>
                {log.data?.items.map((a) => (
                  <Fragment key={a.audit_id}>
                    <tr>
                      <td>{new Date(a.created_at).toLocaleString()}</td>
                      <td>{a.actor_email ?? <span className="muted">system / patient</span>}</td>
                      <td><code>{a.action}</code></td>
                      <td>{a.entity_type}{a.entity_id !== null ? ` #${a.entity_id}` : ""}</td>
                      <td className="actions">{a.details && <button className="link" onClick={() => setOpen(open === a.audit_id ? null : a.audit_id)}>{open === a.audit_id ? "Hide" : "Details"}</button>}</td>
                    </tr>
                    {open === a.audit_id && (
                      <tr><td colSpan={5}><pre>{JSON.stringify(a.details, null, 2)}</pre></td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
            <div className="row pager">
              <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
              <span className="muted small">{total === 0 ? 0 : offset + 1}-{Math.min(offset + PAGE, total)} of {total}</span>
              <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
