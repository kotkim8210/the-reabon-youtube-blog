import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import Sidebar from "@/components/sidebar";
import { WorkspaceProvider } from "@/components/workspace-provider";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { data: mem } = await supabase
    .from("members")
    .select("workspace_id, role, workspaces(name)")
    .limit(1)
    .maybeSingle();

  if (!mem) {
    // 트리거로 자동 생성되지만, 혹시 없으면 안내
    return (
      <div className="p-8 text-sm text-slate-600">
        워크스페이스를 준비 중입니다. 잠시 후 새로고침 해주세요.
      </div>
    );
  }

  const workspaceName =
    (mem.workspaces as unknown as { name: string } | null)?.name ??
    "내 워크스페이스";

  return (
    <WorkspaceProvider
      value={{
        workspaceId: mem.workspace_id,
        workspaceName,
        role: mem.role,
        email: user.email ?? "",
      }}
    >
      <div className="flex min-h-screen bg-white text-slate-800">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-x-hidden p-6">{children}</main>
      </div>
    </WorkspaceProvider>
  );
}
