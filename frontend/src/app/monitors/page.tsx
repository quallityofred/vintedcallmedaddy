import { AnimatedSection } from "@/components/animated-section";
import { AuthGuard } from "@/components/auth-guard";
import { MonitorPreview } from "@/components/monitor-preview";
import { PageShell } from "@/components/page-shell";

export default function MonitorsPage() {
  return (
    <AuthGuard>
      <PageShell
        eyebrow="Monitors"
        title="Manage your Vinted search monitors"
        description="Create, edit, pause, resume, check, and remove user-scoped monitor jobs."
      >
        <AnimatedSection>
          <MonitorPreview />
        </AnimatedSection>
      </PageShell>
    </AuthGuard>
  );
}
