import { Activity, Bell, Clock, Radar } from "lucide-react";

import { AnimatedSection } from "@/components/animated-section";
import { DashboardCard } from "@/components/dashboard-card";
import { MonitorPreview } from "@/components/monitor-preview";
import { PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const cards = [
  { title: "Active monitors", value: "API pending", icon: Radar },
  { title: "Items today", value: "API pending", icon: Activity },
  { title: "Telegram status", value: "API pending", icon: Bell },
  { title: "Last discovery", value: "API pending", icon: Clock },
];

export default function DashboardPage() {
  return (
    <PageShell
      eyebrow="Dashboard shell"
      title="Monitor operations"
      description="A protected-layout preview for the future API-backed dashboard."
    >
      <AnimatedSection className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <DashboardCard key={card.title} {...card} />
        ))}
      </AnimatedSection>

      <AnimatedSection delay={0.08}>
        <MonitorPreview />
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
              No backend calls yet
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            {["/api/v1/auth/me", "/api/v1/auth/csrf", "/api/v1/monitors"].map((endpoint) => (
              <div key={endpoint} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="font-mono text-sm text-emerald-200">{endpoint}</p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  Contract pending. Existing Jinja route remains the source of truth.
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      </AnimatedSection>
    </PageShell>
  );
}
