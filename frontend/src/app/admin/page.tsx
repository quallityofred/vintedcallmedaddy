"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/page-shell";
import { AdminInvites } from "@/components/admin-invites";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRouter } from "next/navigation";

export default function AdminPage() {
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    async function checkAdmin() {
      try {
        const response = await fetch("/api/v1/auth/me");
        const data = await response.json();
        if (data.user?.is_admin) {
          setIsAdmin(true);
        } else {
          router.push("/dashboard");
        }
      } catch {
        router.push("/dashboard");
      } finally {
        setLoading(false);
      }
    }
    void checkAdmin();
  }, [router]);

  if (loading) return null;
  if (!isAdmin) return null;

  return (
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
  );
}
