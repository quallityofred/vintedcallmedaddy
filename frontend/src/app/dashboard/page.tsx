import { AnimatedSection } from "@/components/animated-section";
import { AuthGuard } from "@/components/auth-guard";
import { BackendHealthCard } from "@/components/backend-health-card";
import { SystemStatusCard } from "@/components/system-status";
import { DashboardStats } from "@/components/dashboard-stats";
import { MonitorPreview } from "@/components/monitor-preview";
import { FoundItemsList } from "@/components/found-items-list";
import { PageShell } from "@/components/page-shell";

export default function DashboardPage() {
  return (
    <AuthGuard>
      <PageShell
        eyebrow="Dashboard"
        title="Monitor operations"
        description="Manage your Vinted monitors and track findings."
      >
        <DashboardStats />

        <AnimatedSection delay={0.06}>
          <div className="grid gap-4 xl:grid-cols-2">
            <BackendHealthCard />
            <SystemStatusCard />
          </div>
        </AnimatedSection>

        <AnimatedSection delay={0.08}>
          <MonitorPreview />
        </AnimatedSection>

        <AnimatedSection delay={0.10}>
          <FoundItemsList />
        </AnimatedSection>
      </PageShell>
    </AuthGuard>
  );
}
