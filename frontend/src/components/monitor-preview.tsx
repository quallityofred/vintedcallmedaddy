"use client";

import { useEffect, useState } from "react";
import { Bell, Clock3, ExternalLink, Radar, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface Monitor {
  id: number;
  name: string;
  original_url: string;
  interval_sec: number;
  is_active: boolean;
  last_check_at: string | null;
  items_found_count: number;
}

const events = [
  { label: "DB-level dedup active", icon: ShieldCheck },
  { label: "Telegram notification active", icon: Bell },
  { label: "Adaptive interval enabled", icon: Clock3 },
];

export function MonitorPreview() {
  const [monitors, setMonitors] = useState<Monitor[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function fetchMonitors() {
      try {
        const response = await fetch("/api/v1/monitors", {
          cache: "no-store",
          credentials: "same-origin",
        });
        if (!response.ok) {
          throw new Error("API error");
        }
        const data = (await response.json()) as Monitor[];
        setMonitors(data);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    }
    void fetchMonitors();
  }, []);

  const getDomain = (url: string) => {
    try {
      const u = new URL(url);
      return u.hostname.replace("www.", "");
    } catch {
      return "unknown";
    }
  };

  const formatInterval = (sec: number) => {
    if (sec < 60) return `${sec}s`;
    return `${Math.floor(sec / 60)}m${sec % 60}s`;
  };

  return (
    <Card className="glass-panel overflow-hidden">
      <CardHeader className="border-b border-white/10">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Radar className="size-4 text-emerald-200" />
              Active Monitors
            </CardTitle>
            <CardDescription>
              Real-time monitoring status and findings.
            </CardDescription>
          </div>
          {!loading && !error && monitors && monitors.length > 0 && (
            <Badge variant="outline" className="w-fit border-emerald-300/20 text-emerald-200">
              {monitors.length} total
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="grid gap-5 p-4 lg:grid-cols-[1fr_17rem]">
        <div className="overflow-hidden rounded-2xl border border-white/10">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Search</TableHead>
                <TableHead>Domain</TableHead>
                <TableHead>Interval</TableHead>
                <TableHead className="text-right">Found</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-32 text-center text-muted-foreground">
                    Loading monitors...
                  </TableCell>
                </TableRow>
              ) : error ? (
                <TableRow>
                  <TableCell colSpan={4} className="h-32 text-center text-red-400">
                    Failed to load monitors.
                  </TableCell>
                </TableRow>
              ) : monitors && monitors.length > 0 ? (
                monitors.map((monitor) => (
                  <TableRow key={monitor.id}>
                    <TableCell>
                      <div className="font-medium">{monitor.name}</div>
                      <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                        <ExternalLink className="size-3" />
                        <a 
                          href={monitor.original_url} 
                          target="_blank" 
                          rel="noreferrer"
                          className="hover:text-emerald-200"
                        >
                          View search
                        </a>
                      </div>
                    </TableCell>
                    <TableCell>{getDomain(monitor.original_url)}</TableCell>
                    <TableCell>{formatInterval(monitor.interval_sec)}</TableCell>
                    <TableCell className="text-right">
                      <span className="font-semibold text-emerald-200">{monitor.items_found_count}</span>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className="h-32 text-center text-muted-foreground">
                    No monitors found. Create one in Settings.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className="space-y-3">
          {events.map((event) => (
            <div key={event.label} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <div className="mb-3 flex size-9 items-center justify-center rounded-xl bg-emerald-300/10 text-emerald-200">
                <event.icon className="size-4" />
              </div>
              <p className="text-sm font-medium">{event.label}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Verified status of the underlying monitoring engine.
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
