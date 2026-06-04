"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Loader2, Radar } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type DashboardStats = {
  active_monitors_count: number;
  paused_monitors_count: number;
};

export function MonitorsSummaryCard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadStats() {
      try {
        const response = await fetch("/api/v1/dashboard/stats", {
          cache: "no-store",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
        });
        if (!response.ok) {
          throw new Error("Unable to load monitor summary");
        }
        const payload = (await response.json()) as DashboardStats;
        if (active) {
          setStats(payload);
        }
      } catch {
        if (active) {
          setError(true);
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadStats();
    return () => {
      active = false;
    };
  }, []);

  const total = stats ? stats.active_monitors_count + stats.paused_monitors_count : null;

  return (
    <Card className="glass-panel overflow-hidden">
      <CardHeader className="border-b border-white/10 p-4 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <CardTitle className="flex items-center gap-2">
              <Radar className="size-4 text-emerald-200" />
              Monitors
            </CardTitle>
            <CardDescription>
              Overview of your search coverage. Full creation, edit, and control actions live on the monitors page.
            </CardDescription>
          </div>
          <Link href="/monitors" className={cn(buttonVariants(), "w-full sm:w-auto")}>
            Manage monitors
            <ArrowRight className="size-4" />
          </Link>
        </div>
      </CardHeader>
      <CardContent className="p-4 sm:p-6">
        {loading ? (
          <div className="flex h-24 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin text-emerald-200" />
            Loading monitor summary
          </div>
        ) : error ? (
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-muted-foreground">
            Monitor counts are temporarily unavailable. Use the management page to view the current monitor list.
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-3">
            <SummaryMetric label="Active" value={stats?.active_monitors_count ?? 0} />
            <SummaryMetric label="Paused" value={stats?.paused_monitors_count ?? 0} />
            <SummaryMetric label="Total" value={total ?? 0} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
