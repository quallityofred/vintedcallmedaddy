"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Server, Wifi, WifiOff } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type BackendHealth = {
  status?: string;
  scheduler_jobs?: number;
  bots_running?: number;
};

type HealthState =
  | { status: "loading"; checkedAt: Date | null; data: null; message: null }
  | { status: "reachable"; checkedAt: Date; data: BackendHealth; message: null }
  | { status: "unreachable"; checkedAt: Date; data: null; message: string };

const initialState: HealthState = {
  status: "loading",
  checkedAt: null,
  data: null,
  message: null,
};

function formatCheckedAt(checkedAt: Date | null) {
  if (!checkedAt) {
    return "Checking now";
  }
  return checkedAt.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function BackendHealthCard() {
  const [health, setHealth] = useState<HealthState>(initialState);

  const fetchHealth = useCallback(async (): Promise<HealthState> => {
    try {
      const response = await fetch("/api/health", {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        throw new Error("Backend health check failed");
      }

      const data = (await response.json()) as BackendHealth;
      return {
        status: "reachable",
        checkedAt: new Date(),
        data,
        message: null,
      };
    } catch {
      return {
        status: "unreachable",
        checkedAt: new Date(),
        data: null,
        message: "Backend health endpoint is not reachable through the frontend proxy.",
      };
    }
  }, []);

  const checkHealth = useCallback(async () => {
    setHealth((current) => ({
      status: "loading",
      checkedAt: current.checkedAt,
      data: null,
      message: null,
    }));
    setHealth(await fetchHealth());
  }, [fetchHealth]);

  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      const nextHealth = await fetchHealth();
      if (!cancelled) {
        setHealth(nextHealth);
      }
    }

    void loadHealth();

    const interval = setInterval(loadHealth, 15 * 1000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [fetchHealth]);

  const isReachable = health.status === "reachable";
  const isLoading = health.status === "loading";
  const StatusIcon = isReachable ? Wifi : health.status === "unreachable" ? WifiOff : Server;

  return (
    <Card className="glass-panel overflow-hidden">
      <CardHeader className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="flex size-9 items-center justify-center rounded-2xl bg-emerald-300/10 text-emerald-200 ring-1 ring-emerald-300/15">
              <StatusIcon className="size-4" />
            </span>
            <CardTitle>Backend connectivity</CardTitle>
          </div>
          <CardDescription>
            Public health probe via the Next.js `/api/health` proxy.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className={cn(
              "w-fit",
              isReachable
                ? "border-emerald-300/20 text-emerald-200"
                : health.status === "unreachable"
                  ? "border-red-300/20 text-red-200"
                  : "border-white/15 text-muted-foreground",
            )}
          >
            {isReachable ? "Reachable" : health.status === "unreachable" ? "Unreachable" : "Checking"}
          </Badge>
          <Button
            aria-label="Refresh backend health"
            className="border-white/10 bg-white/[0.04]"
            disabled={isLoading}
            onClick={checkHealth}
            size="icon"
            type="button"
            variant="outline"
          >
            <RefreshCw className={cn("size-4", isLoading && "animate-spin")} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {["Status", "Jobs", "Bots"].map((item) => (
              <div key={item} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <Skeleton className="h-3 w-16 bg-white/10" />
                <Skeleton className="mt-2 h-5 w-12 bg-white/10" />
              </div>
            ))}
            <div className="col-span-1 rounded-2xl border border-white/10 bg-white/[0.03] p-4 sm:col-span-3">
                <Skeleton className="h-3 w-16 bg-white/10" />
                <Skeleton className="mt-2 h-5 w-32 bg-white/10" />
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <HealthMetric label="Status" value={health.data?.status ?? "unavailable"} />
            <HealthMetric label="Jobs" value={String(health.data?.scheduler_jobs ?? 0)} />
            <HealthMetric label="Bots" value={String(health.data?.bots_running ?? 0)} />
            <div className="col-span-1 sm:col-span-3">
                <HealthMetric label="Checked" value={formatCheckedAt(health.checkedAt)} />
            </div>
          </div>
        )}

        {health.status === "unreachable" ? (
          <p className="rounded-2xl border border-red-300/10 bg-red-400/10 px-4 py-3 text-sm text-red-100">
            {health.message}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function HealthMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
      <p className="mt-2 truncate text-lg font-semibold text-foreground">{value}</p>
    </div>
  );
}
