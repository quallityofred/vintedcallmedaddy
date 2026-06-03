"use client";

import { useEffect, useState } from "react";
import { Loader2, Server, Database, Bot, Radar } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface SystemStatus {
  scheduler_running: boolean;
  active_jobs_count: number;
  bots_running_count: number;
  database_status: string;
}

export function SystemStatusCard() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchStatus() {
      try {
        const response = await fetch("/api/v1/system/status", {
          cache: "no-store",
          credentials: "same-origin",
        });
        if (response.ok) {
          const data = await response.json();
          setStatus(data);
        }
      } catch {
        // Ignore errors
      } finally {
        setLoading(false);
      }
    }
    void fetchStatus();
  }, []);

  if (loading) {
    return (
      <Card className="glass-panel">
        <CardContent className="flex h-32 items-center justify-center">
          <Loader2 className="size-6 animate-spin opacity-20" />
        </CardContent>
      </Card>
    );
  }

  if (!status) return null;

  const items = [
    { label: "Scheduler", value: status.scheduler_running ? "Running" : "Stopped", icon: Radar },
    { label: "Active Jobs", value: status.active_jobs_count, icon: Server },
    { label: "Bots Running", value: status.bots_running_count, icon: Bot },
    { label: "Database", value: status.database_status, icon: Database },
  ];

  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle>System Status</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3">
        {items.map((item) => (
          <div key={item.label} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <p className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
              <item.icon className="size-3" />
              {item.label}
            </p>
            <p className="mt-2 truncate text-lg font-semibold text-foreground">{item.value}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
