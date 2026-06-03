import { AnimatedSection } from "@/components/animated-section";
import { BackendHealthCard } from "@/components/backend-health-card";
import { DashboardStats } from "@/components/dashboard-stats";
import { MonitorPreview } from "@/components/monitor-preview";
import { FoundItemsList } from "@/components/found-items-list";
import { PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardPage() {
  return (
    <PageShell
      eyebrow="Dashboard"
      title="Monitor operations"
      description="Manage your Vinted monitors and track findings."
    >
      <DashboardStats />

      <AnimatedSection delay={0.06}>
        <BackendHealthCard />
      </AnimatedSection>

      <AnimatedSection delay={0.08}>
        <MonitorPreview />
      </AnimatedSection>

      <AnimatedSection delay={0.10}>
        <FoundItemsList />
      </AnimatedSection>

      <AnimatedSection delay={0.12}>
        <Card className="glass-panel">
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>API readiness checklist</CardTitle>
              <CardDescription>
                Placeholder guidance for the next backend API phase.
              </CardDescription>
            </div>
            <Badge variant="outline" className="w-fit border-emerald-300/20 text-emerald-200">
              Health & Stats active
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            {["/api/v1/auth/me", "/api/v1/dashboard/stats", "/api/v1/monitors", "/api/v1/items"].map((endpoint) => (
              <div key={endpoint} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="font-mono text-sm text-emerald-200">{endpoint}</p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {endpoint === "/api/v1/dashboard/stats"
                    ? "Live data. Dashboard cards now consume this user-scoped JSON endpoint."
                    : endpoint === "/api/v1/auth/me"
                    ? "Live data. Used for session validation and user profile."
                    : endpoint === "/api/v1/items"
                    ? "Live data. Found items list integrated."
                    : "Contract pending."}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      </AnimatedSection>
    </PageShell>
  );
}
