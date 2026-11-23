export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/v1";

const TOKEN_KEY = "cc_staff_token";
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

function detailText(body: unknown): string | null {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((x: { msg?: string; loc?: unknown[] }) => {
        const field = Array.isArray(x.loc) && x.loc.length > 1 ? `${String(x.loc[x.loc.length - 1])}: ` : "";
        return `${field}${(x.msg ?? "Invalid value").replace("Value error, ", "")}`;
      })
      .join("; ");
  }
  return null;
}

async function request<T>(method: string, path: string, body?: unknown, query?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(API_URL + path);
  Object.entries(query ?? {}).forEach(([k, v]) => v !== undefined && v !== "" && url.searchParams.set(k, String(v)));
  const headers: Record<string, string> = { accept: "application/json" };
  const token = tokenStore.get();
  if (token) headers.authorization = `Bearer ${token}`;
  if (body !== undefined) headers["content-type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Cannot reach the server. Is the API running?", 0);
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    if (res.status === 401 && token) onUnauthorized();
    throw new ApiError(detailText(data) ?? `Request failed (${res.status})`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, string | number | undefined>) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  /** For images such as the clinic check-in QR code (they need the login header, so <img src> will not do). */
  async blobUrl(path: string): Promise<string> {
    const token = tokenStore.get();
    const res = await fetch(API_URL + path, { headers: token ? { authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new ApiError(`Could not load image (${res.status})`, res.status);
    return URL.createObjectURL(await res.blob());
  },
};

// ---------- types (match the FastAPI schemas) ----------
export type Role = "receptionist" | "nurse" | "clinic_manager" | "inventory_manager" | "system_admin";

export interface Me {
  staff_id: number;
  first_name: string;
  last_name: string;
  email: string;
  role_names: Role[];
  branch_ids: number[];
}
export interface Branch {
  branch_id: number;
  branch_name: string;
  address: string | null;
  status: string;
}
export interface BranchService {
  service_id: number;
  service_name: string;
  available: boolean;
  in_stock: boolean;
}
export interface Slot {
  slot_id: number;
  slot_date: string;
  start_time: string;
  end_time: string;
  spots_left: number;
  available: boolean;
}
export interface StaffAppointment {
  appointment_id: number;
  appointment_reference: string;
  status: string;
  service_name: string;
  slot_date: string;
  start_time: string;
  end_time: string;
  patient_name: string;
  patient_phone: string;
  membership_number: string | null;
}
export interface PatientHit {
  patient_id: number;
  first_name: string;
  last_name: string;
  phone: string;
  membership_number: string | null;
}
export interface QueueRow {
  queue_id: number;
  queue_number: number;
  queue_status: string;
  appointment_reference: string;
  service_name: string;
  appointment_time: string;
  check_in_time: string;
  patient_name: string;
  people_ahead: number;
  estimated_wait_minutes: number;
}
export interface StockRow {
  item_id: number;
  item_name: string;
  item_category: string | null;
  unit: string;
  quantity: number;
  minimum_quantity: number;
  availability_status: string;
  low_stock: boolean;
}
export interface Item {
  item_id: number;
  item_name: string;
  item_category: string | null;
  unit: string;
}
export interface Counts {
  total: number;
  completed: number;
  cancelled: number;
  no_show: number;
  pending: number;
}
export interface AppointmentReport {
  totals: Counts;
  completion_rate: number;
  cancellation_rate: number;
  by_day: (Counts & { date: string })[];
  by_service: (Counts & { id: number; name: string })[];
}
export interface QueueReport {
  checked_in: number;
  by_status: Record<string, number>;
  avg_wait_minutes: number | null;
  avg_service_minutes: number | null;
}
export interface BranchPerformance {
  branch_id: number;
  branch_name: string;
  appointments: Counts;
  completion_rate: number;
  cancellation_rate: number;
  no_show_rate: number;
  queue_checked_in: number;
  avg_wait_minutes: number | null;
}
export interface SystemSummary {
  patients: number;
  active_staff: number;
  active_branches: number;
  active_services: number;
  appointments_today: number;
  appointments_this_month: number;
  queue_check_ins_today: number;
  low_stock_items: number;
}
export interface AuditEntry {
  audit_id: number;
  created_at: string;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: number | null;
  details: Record<string, unknown> | null;
}
export interface AuditPage {
  total: number;
  limit: number;
  offset: number;
  items: AuditEntry[];
}

export const shortTime = (t: string) => t.slice(0, 5);
export const todayIso = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in the browser's timezone
export const pct = (x: number) => `${Math.round(x * 100)}%`;
