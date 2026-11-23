import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, Branch, Me, Role, setUnauthorizedHandler, tokenStore } from "./api";

interface AuthValue {
  me: Me | null;
  loading: boolean;
  branches: Branch[]; // only the branches this person may work in
  branchId: number | null;
  setBranchId: (id: number) => void;
  has: (...roles: Role[]) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>; // reload my branches after creating or changing one
  notice: string | null;
}

const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchIdState] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const logout = useCallback(() => {
    tokenStore.clear();
    setMe(null);
    setBranches([]);
    setBranchIdState(null);
  }, []);

  const loadProfile = useCallback(async () => {
    const profile = await api.get<Me>("/auth/staff/me");
    const all = await api.get<Branch[]>("/branches");
    const isAdmin = profile.role_names.includes("system_admin");
    const mine = all.filter((b) => isAdmin || profile.branch_ids.includes(b.branch_id));
    setMe(profile);
    setBranches(mine);
    const saved = Number(localStorage.getItem("cc_branch"));
    setBranchIdState(mine.find((b) => b.branch_id === saved)?.branch_id ?? mine[0]?.branch_id ?? null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setNotice("Your session expired. Please sign in again.");
      logout();
    });
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    loadProfile()
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, [loadProfile, logout]);

  const value = useMemo<AuthValue>(
    () => ({
      me,
      loading,
      branches,
      branchId,
      notice,
      setBranchId: (id) => {
        localStorage.setItem("cc_branch", String(id));
        setBranchIdState(id);
      },
      has: (...roles) => !!me && roles.some((r) => me.role_names.includes(r)),
      login: async (email, password) => {
        const t = await api.post<{ access_token: string }>("/auth/staff/login", { email: email.trim(), password });
        tokenStore.set(t.access_token);
        setNotice(null);
        await loadProfile();
      },
      refresh: loadProfile,
      logout,
    }),
    [me, loading, branches, branchId, notice, loadProfile, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
