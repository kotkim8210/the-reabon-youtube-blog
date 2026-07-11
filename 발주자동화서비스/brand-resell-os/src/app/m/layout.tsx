import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { WorkspaceProvider } from "@/components/workspace-provider";

export default async function MobileLayout({
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
    return <div className="p-6 text-sm">워크스페이스 준비 중…</div>;
  }

  const workspaceName =
    (mem.workspaces as unknown as { name: string } | null)?.name ?? "";

  return (
    <WorkspaceProvider
      value={{
        workspaceId: mem.workspace_id,
        workspaceName,
        role: mem.role,
        email: user.email ?? "",
      }}
    >
      <div className="mx-auto min-h-screen max-w-md bg-white text-slate-800">
        {children}
      </div>
    </WorkspaceProvider>
  );
}
