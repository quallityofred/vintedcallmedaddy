"use client";

import Link from "next/link";
import { ArrowRight, Bell, Database, Gauge, Radar, ShieldCheck, Sparkles } from "lucide-react";

import { AnimatedSection } from "@/components/animated-section";
import { DashboardCard } from "@/components/dashboard-card";
import { SectionHeading } from "@/components/section-heading";
import { buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/auth-context";

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

const principles = [
  {
    title: "Backend-owned runtime",
    value: "FastAPI continues to own auth, sessions, scheduler, scraper, and Telegram bots.",
    icon: Database,
  },
  {
    title: "Safe controls",
    value: "Every workflow keeps auth, CSRF, ownership, and backend runtime boundaries intact.",
    icon: ShieldCheck,
  },
  {
    title: "Operator density",
    value: "Dashboards stay compact, scannable, and responsive on small screens.",
    icon: Gauge,
  },
];

export default function Home() {
  const { user } = useAuth();
  
  return (
    <main className="min-h-screen overflow-hidden">
      <section className="relative isolate soft-grid">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_50%_0%,rgba(74,222,128,0.12),transparent_34rem)]" />
        <div className="mx-auto grid min-h-screen max-w-7xl items-center gap-12 px-6 py-10 lg:grid-cols-[1fr_0.9fr] lg:px-10">
          <AnimatedSection className="space-y-8">
            <Badge className="w-fit border-emerald-300/20 bg-emerald-300/10 text-emerald-200">
              Live monitoring console
            </Badge>
            <div className="space-y-5">
              <h1 className="max-w-4xl text-5xl font-semibold tracking-tight text-balance sm:text-6xl lg:text-7xl">
                Vinted Monitor dashboard, rebuilt for focused operations.
              </h1>
              <p className="max-w-2xl text-lg leading-8 text-muted-foreground">
                A focused control surface for Vinted search monitors, Telegram delivery, and item discovery.
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              {user ? (
                <Link href="/dashboard" className={cn(buttonVariants({ size: "lg" }), "h-11 px-5")}>
                  Open dashboard
                  <ArrowRight className="size-4" />
                </Link>
              ) : (
                <>
                  <Link href="/login" className={cn(buttonVariants({ size: "lg" }), "h-11 px-5")}>
                    Sign in
                  </Link>
                  <Link
                    href="/register"
                    className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-11 px-5")}
                  >
                    Create account
                  </Link>
                </>
              )}
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
            <div className="flex aspect-square items-center justify-center rounded-3xl bg-emerald-300/5 p-12 text-emerald-200/50">
              <Radar className="size-32" />
            </div>
          </AnimatedSection>
        </div>
      </section>
      <section className="mx-auto max-w-7xl px-6 pb-16 lg:px-10">
        <AnimatedSection className="mb-8">
          <SectionHeading
            eyebrow="Product overview"
            title="A command center for search monitoring, deduplication, and notifications."
            description="Review monitor health, recent findings, and notification readiness from one responsive interface."
          />
        </AnimatedSection>
        <AnimatedSection delay={0.08} className="glass-panel mb-8 rounded-3xl p-6 sm:p-8">
          <div className="grid gap-4 md:grid-cols-3">
            <DashboardCard title="Monitor health" value="Track active and paused searches from the dashboard." icon={Radar} compact />
            <DashboardCard title="Item discovery" value="Review newly found items without opening each monitor." icon={Bell} compact />
            <DashboardCard title="Safe controls" value="Manage full monitor actions from the protected monitors page." icon={ShieldCheck} compact />
          </div>
        </AnimatedSection>
        <AnimatedSection delay={0.12} className="grid gap-4 md:grid-cols-3">
          {principles.map((principle) => (
            <DashboardCard key={principle.title} {...principle} compact />
          ))}
        </AnimatedSection>
        <AnimatedSection delay={0.16} className="glass-panel mt-8 rounded-3xl p-6 sm:p-8">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="mb-3 flex items-center gap-2 text-sm text-emerald-200">
                <Sparkles className="size-4" />
                Reliability built-in
              </div>
              <h2 className="text-2xl font-semibold tracking-tight">Reliable monitoring, every time.</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                Automated search tracking, intelligent deduplication, and fast Telegram notifications.
              </p>
            </div>
            <Link href="/settings" className={buttonVariants({ variant: "secondary" })}>
              View settings
            </Link>
          </div>
        </AnimatedSection>
      </section>
    </main>
  );
}
