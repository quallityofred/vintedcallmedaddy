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
      <CardContent className="grid grid-cols-2 gap-4">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <item.icon className="size-4 text-emerald-200" />
            <div>
              <p className="text-xs text-muted-foreground">{item.label}</p>
              <p className="text-sm font-medium">{item.value}</p>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
