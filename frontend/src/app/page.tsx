import Link from "next/link";
import { ArrowRight, Bell, Radar, ShieldCheck, Sparkles } from "lucide-react";

import { AnimatedSection } from "@/components/animated-section";
import { DashboardCard } from "@/components/dashboard-card";
import { SplineHero } from "@/components/spline-hero";
import { buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const features = [
  {
    title: "Monitor URLs",
    description: "Track Vinted searches across domains without touching the scraper runtime.",
    icon: Radar,
  },
  {
    title: "Notify fast",
    description: "Keep Telegram delivery visible while the backend owns tokens and sessions.",
    icon: Bell,
  },
  {
    title: "Stay isolated",
    description: "Build the new UI around user-scoped API contracts and safe defaults.",
    icon: ShieldCheck,
  },
];

export default function Home() {
  return (
    <main className="min-h-screen overflow-hidden">
      <section className="relative isolate soft-grid">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_50%_0%,rgba(74,222,128,0.12),transparent_34rem)]" />
        <div className="mx-auto grid min-h-screen max-w-7xl items-center gap-12 px-6 py-10 lg:grid-cols-[1fr_0.9fr] lg:px-10">
          <AnimatedSection className="space-y-8">
            <Badge className="w-fit border-emerald-300/20 bg-emerald-300/10 text-emerald-200">
              Phase 1 frontend foundation
            </Badge>
            <div className="space-y-5">
              <h1 className="max-w-4xl text-5xl font-semibold tracking-tight text-balance sm:text-6xl lg:text-7xl">
                Vinted Monitor dashboard, rebuilt for focused operations.
              </h1>
              <p className="max-w-2xl text-lg leading-8 text-muted-foreground">
                A Next.js shell for the existing FastAPI service. Jinja pages stay online while the new frontend grows behind stable API boundaries.
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <Link href="/dashboard" className={cn(buttonVariants({ size: "lg" }), "h-11 px-5")}>
                Open dashboard shell
                <ArrowRight className="size-4" />
              </Link>
              <Link
                href="/login"
                className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}
              >
                Preview login
              </Link>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {features.map((feature) => (
                <DashboardCard
                  key={feature.title}
                  title={feature.title}
                  value={feature.description}
                  icon={feature.icon}
                  compact
                />
              ))}
            </div>
          </AnimatedSection>

          <AnimatedSection delay={0.12}>
            <SplineHero />
          </AnimatedSection>
        </div>
      </section>
      <section className="mx-auto max-w-7xl px-6 pb-16 lg:px-10">
        <AnimatedSection className="glass-panel rounded-3xl p-6 sm:p-8">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="mb-3 flex items-center gap-2 text-sm text-emerald-200">
                <Sparkles className="size-4" />
                Ready for incremental migration
              </div>
              <h2 className="text-2xl font-semibold tracking-tight">Backend behavior remains untouched.</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                This frontend starts as a visual and routing foundation. Auth, CSRF, scheduler, scraper, Telegram, and deduplication stay in FastAPI until explicit API work begins.
              </p>
            </div>
            <Link href="/settings" className={buttonVariants({ variant: "secondary" })}>
              View settings shell
            </Link>
          </div>
        </AnimatedSection>
      </section>
    </main>
  );
}
