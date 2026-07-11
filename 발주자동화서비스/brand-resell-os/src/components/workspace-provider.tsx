"use client";

import { createContext, useContext } from "react";

export interface WorkspaceCtx {
  workspaceId: string;
  workspaceName: string;
  role: "owner" | "staff" | "warehouse";
  email: string;
}

const Ctx = createContext<WorkspaceCtx | null>(null);

export function WorkspaceProvider({
  value,
  children,
}: {
  value: WorkspaceCtx;
  children: React.ReactNode;
}) {
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWorkspace() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return v;
}
