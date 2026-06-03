import { PageShell } from "@/components/page-shell";
import { AuthGuard } from "@/components/auth-guard";
import { AdminInvites } from "@/components/admin-invites";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AdminPage() {
  return (
    <AuthGuard requireAdmin>
      <PageShell eyebrow="Admin" title="Administration" description="Manage system invites and logs.">
        <div className="grid gap-6">
          <AdminInvites />
          <Card className="glass-panel">
            <CardHeader>
              <CardTitle>System Logs</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-muted-foreground">Logs access is restricted for security.</p>
            </CardContent>
          </Card>
        </div>
      </PageShell>
    </AuthGuard>
  );
}
