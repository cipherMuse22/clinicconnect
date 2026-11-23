import { FormEvent, useState } from "react";

import { api, Item, StockRow } from "../api";
import { useAuth } from "../auth";
import { Badge, Card, ErrorBox, errText, Loading, Modal, PageHeader, useAsync } from "../ui";

type MovementType = "received" | "used" | "adjusted";

export default function InventoryPage() {
  const { branchId, has } = useAuth();
  const editor = has("inventory_manager", "system_admin");
  const [msg, setMsg] = useState<string | null>(null);
  const [move, setMove] = useState<StockRow | null>(null);
  const [adding, setAdding] = useState(false);
  const [onlyLow, setOnlyLow] = useState(false);

  const stock = useAsync(() => api.get<StockRow[]>(`/branches/${branchId}/stock`), [branchId]);
  const rows = (stock.data ?? []).filter((r) => !onlyLow || r.low_stock);
  const lowCount = (stock.data ?? []).filter((r) => r.low_stock).length;

  return (
    <>
      <PageHeader title="Inventory">
        <label className="row"><input type="checkbox" checked={onlyLow} onChange={(e) => setOnlyLow(e.target.checked)} /> Low stock only ({lowCount})</label>
        {editor && <button className="primary" onClick={() => setAdding(true)}>Add item</button>}
      </PageHeader>
      {msg && <div className="notice">{msg}</div>}
      <Card>
        {stock.loading ? (
          <Loading />
        ) : stock.error ? (
          <ErrorBox message={stock.error} onRetry={() => void stock.reload()} />
        ) : rows.length === 0 ? (
          <p className="muted">{onlyLow ? "Nothing is low on stock." : "No stock records for this branch yet."}</p>
        ) : (
          <table>
            <thead>
              <tr><th>Item</th><th>Category</th><th className="num">In stock</th><th className="num">Minimum</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.item_id} className={r.low_stock ? "low" : ""}>
                  <td>{r.item_name}</td>
                  <td>{r.item_category ?? "-"}</td>
                  <td className="num"><strong>{r.quantity}</strong> {r.unit}</td>
                  <td className="num">{r.minimum_quantity}</td>
                  <td>{r.low_stock ? <Badge status="low">Low stock</Badge> : <Badge status={r.availability_status} />}</td>
                  <td className="actions">{editor && <button onClick={() => setMove(r)}>Update stock</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {move && (
        <MovementModal
          branchId={branchId!}
          row={move}
          onClose={() => setMove(null)}
          onDone={(m) => {
            setMove(null);
            setMsg(m);
            void stock.reload(true);
          }}
        />
      )}
      {adding && (
        <AddItemModal
          branchId={branchId!}
          have={(stock.data ?? []).map((s) => s.item_id)}
          onClose={() => setAdding(false)}
          onDone={(m) => {
            setAdding(false);
            setMsg(m);
            void stock.reload(true);
          }}
        />
      )}
    </>
  );
}

function MovementModal({ branchId, row, onClose, onDone }: { branchId: number; row: StockRow; onClose: () => void; onDone: (m: string) => void }) {
  const [type, setType] = useState<MovementType>("received");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api.post<{ quantity_after: number }>(`/branches/${branchId}/stock/${row.item_id}/movements`, {
        movement_type: type,
        quantity: Number(qty),
        reason: reason.trim() || null,
      });
      onDone(`${row.item_name}: now ${r.quantity_after} ${row.unit}.`);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <Modal title={`Update ${row.item_name}`} onClose={onClose}>
      <form onSubmit={submit} className="form">
        {error && <div className="error">{error}</div>}
        <p className="muted">Currently {row.quantity} {row.unit}.</p>
        <label>What happened?
          <select value={type} onChange={(e) => setType(e.target.value as MovementType)}>
            <option value="received">Stock received (adds)</option>
            <option value="used">Stock used (removes)</option>
            <option value="adjusted">Stock count correction (+ or -)</option>
          </select>
        </label>
        <label>Quantity{type === "adjusted" ? " (use a minus to remove)" : ""}
          <input type="number" value={qty} onChange={(e) => setQty(e.target.value)} min={type === "adjusted" ? undefined : 1} required />
        </label>
        <label>Reason{type === "adjusted" ? " (required)" : " (optional)"}
          <input value={reason} onChange={(e) => setReason(e.target.value)} required={type === "adjusted"} />
        </label>
        <button className="primary">Save</button>
      </form>
    </Modal>
  );
}

function AddItemModal({ branchId, have, onClose, onDone }: { branchId: number; have: number[]; onClose: () => void; onDone: (m: string) => void }) {
  const items = useAsync(() => api.get<Item[]>("/inventory/items"), []);
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [itemId, setItemId] = useState("");
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [unit, setUnit] = useState("units");
  const [initial, setInitial] = useState("0");
  const [min, setMin] = useState("10");
  const [error, setError] = useState<string | null>(null);

  const available = (items.data ?? []).filter((i) => !have.includes(i.item_id));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      let id = Number(itemId);
      if (mode === "new") {
        const created = await api.post<Item>("/inventory/items", { item_name: name.trim(), item_category: category.trim() || null, unit: unit.trim() });
        id = created.item_id;
      }
      await api.post(`/branches/${branchId}/stock`, { item_id: id, initial_quantity: Number(initial), minimum_quantity: Number(min) });
      onDone("Item added to this branch.");
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <Modal title="Add an item to this branch" onClose={onClose}>
      <form onSubmit={submit} className="form">
        {error && <div className="error">{error}</div>}
        <div className="row">
          <label className="row"><input type="radio" checked={mode === "existing"} onChange={() => setMode("existing")} /> Existing item</label>
          <label className="row"><input type="radio" checked={mode === "new"} onChange={() => setMode("new")} /> New item</label>
        </div>
        {mode === "existing" ? (
          <label>Item
            <select value={itemId} onChange={(e) => setItemId(e.target.value)} required>
              <option value="">Choose…</option>
              {available.map((i) => <option key={i.item_id} value={i.item_id}>{i.item_name}</option>)}
            </select>
          </label>
        ) : (
          <>
            <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
            <label>Category<input value={category} onChange={(e) => setCategory(e.target.value)} /></label>
            <label>Unit<input value={unit} onChange={(e) => setUnit(e.target.value)} required /></label>
          </>
        )}
        <label>Starting quantity<input type="number" min={0} value={initial} onChange={(e) => setInitial(e.target.value)} required /></label>
        <label>Warn me when below<input type="number" min={0} value={min} onChange={(e) => setMin(e.target.value)} required /></label>
        <button className="primary">Add</button>
      </form>
    </Modal>
  );
}
