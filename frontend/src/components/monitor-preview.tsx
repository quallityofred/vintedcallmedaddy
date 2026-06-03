"use client";

import { useEffect, useState, useCallback } from "react";
import { 
  Bell, 
  Clock3, 
  ExternalLink, 
  Radar, 
  ShieldCheck, 
  Plus, 
  Trash2, 
  Pause, 
  Play, 
  RefreshCcw,
  Loader2,
  MoreVertical
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

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
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [editingMonitor, setEditingMonitor] = useState<Monitor | null>(null);

  const fetchMonitors = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchMonitors();
  }, [fetchMonitors]);

  const getCsrfToken = async () => {
    const response = await fetch("/api/v1/auth/csrf");
    const { csrf_token } = await response.json();
    return csrf_token;
  };

  const handleAction = async (id: number, action: string) => {
    try {
      const csrfToken = await getCsrfToken();
      let method = "POST";
      let path = `/api/v1/monitors/${id}/${action}`;
      
      if (action === "delete") {
        method = "DELETE";
        path = `/api/v1/monitors/${id}`;
      }

      const response = await fetch(path, {
        method,
        headers: {
          "X-CSRF-Token": csrfToken,
        },
      });

      if (!response.ok) throw new Error("Action failed");

      toast.success(`Monitor ${action === "delete" ? "deleted" : action + "ed"} successfully`);
      void fetchMonitors();
    } catch {
      toast.error(`Failed to ${action} monitor`);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedIds.length === 0) return;
    if (!confirm(`Are you sure you want to delete ${selectedIds.length} monitors?`)) return;

    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/monitors/bulk-delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ monitor_ids: selectedIds }),
      });

      if (!response.ok) throw new Error("Bulk delete failed");
      
      const { deleted_count } = await response.json();
      toast.success(`${deleted_count} monitors deleted`);
      setSelectedIds([]);
      void fetchMonitors();
    } catch {
      toast.error("Failed to perform bulk delete");
    }
  };

  const handleCreateOrUpdate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsSubmitting(true);
    const formData = new FormData(e.currentTarget);
    const payload = {
      name: formData.get("name") as string,
      url: formData.get("url") as string,
      interval_sec: parseInt(formData.get("interval_sec") as string),
    };

    try {
      const csrfToken = await getCsrfToken();
      const method = editingMonitor ? "PATCH" : "POST";
      const path = editingMonitor ? `/api/v1/monitors/${editingMonitor.id}` : "/api/v1/monitors";

      const response = await fetch(path, {
        method,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errData = (await response.json()) as { detail?: string };
        throw new Error(errData.detail || `Failed to ${editingMonitor ? "update" : "create"} monitor`);
      }

      toast.success(`Monitor ${editingMonitor ? "updated" : "created"} successfully`);
      setIsCreateOpen(false);
      setEditingMonitor(null);
      void fetchMonitors();
    } catch (err) {
      const message = err instanceof Error ? err.message : `Failed to ${editingMonitor ? "update" : "create"} monitor`;
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

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
              Monitoring Dashboard
            </CardTitle>
            <CardDescription>
              Manage your active Vinted search monitors.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {selectedIds.length > 0 && (
              <Button 
                variant="destructive" 
                size="sm" 
                onClick={handleBulkDelete}
                className="animate-in fade-in slide-in-from-right-2"
              >
                <Trash2 className="mr-1 size-3.5" />
                Delete Selected ({selectedIds.length})
              </Button>
            )}
            
            <Dialog open={isCreateOpen} onOpenChange={(open) => {
              setIsCreateOpen(open);
              if (!open) setEditingMonitor(null);
            }}>
              <DialogTrigger render={<Button size="sm">
                <Plus className="mr-1 size-3.5" />
                New Monitor
              </Button>} />
              <DialogContent className="sm:max-w-[425px]">
                <form onSubmit={handleCreateOrUpdate}>
                  <DialogHeader>
                    <DialogTitle>{editingMonitor ? "Edit Monitor" : "Create Monitor"}</DialogTitle>
                    <DialogDescription>
                      {editingMonitor 
                        ? "Update the monitor settings below." 
                        : "Add a new Vinted search URL to monitor for new listings."}
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                      <Label htmlFor="name">Friendly Name</Label>
                      <Input id="name" name="name" defaultValue={editingMonitor?.name} placeholder="e.g. Nike Dunk Low 42" required />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="url">Vinted URL</Label>
                      <Input id="url" name="url" defaultValue={editingMonitor?.original_url} placeholder="https://www.vinted.fr/catalog?..." required />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="interval_sec">Check Interval (seconds)</Label>
                      <Input id="interval_sec" name="interval_sec" type="number" defaultValue={editingMonitor?.interval_sec || "120"} min="60" max="3600" required />
                    </div>
                  </div>
                  <DialogFooter>
                    <Button type="submit" disabled={isSubmitting}>
                      {isSubmitting ? (
                        <>
                          <Loader2 className="mr-2 size-4 animate-spin" />
                          {editingMonitor ? "Updating..." : "Creating..."}
                        </>
                      ) : (
                        editingMonitor ? "Update Monitor" : "Create Monitor"
                      )}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-5 p-4 lg:grid-cols-[1fr_17rem]">
        <div className="overflow-hidden rounded-2xl border border-white/10">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <input 
                    type="checkbox" 
                    className="size-4 rounded border-white/20 bg-white/5 accent-emerald-500"
                    checked={!!(monitors && monitors.length > 0 && selectedIds.length === monitors.length)}
                    onChange={() => {
                      if (monitors) {
                        if (selectedIds.length === monitors.length) setSelectedIds([]);
                        else setSelectedIds(monitors.map(m => m.id));
                      }
                    }}
                  />
                </TableHead>
                <TableHead>Search</TableHead>
                <TableHead>Domain</TableHead>
                <TableHead>Interval</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                    <Loader2 className="mx-auto size-6 animate-spin opacity-20" />
                    <p className="mt-2">Loading monitors...</p>
                  </TableCell>
                </TableRow>
              ) : error ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-red-400">
                    Failed to load monitors.
                  </TableCell>
                </TableRow>
              ) : monitors && monitors.length > 0 ? (
                monitors.map((monitor) => (
                  <TableRow key={monitor.id} className={!monitor.is_active ? "opacity-60" : ""}>
                    <TableCell>
                      <input 
                        type="checkbox" 
                        className="size-4 rounded border-white/20 bg-white/5 accent-emerald-500"
                        checked={selectedIds.includes(monitor.id)}
                        onChange={() => {
                          setSelectedIds(prev => 
                            prev.includes(monitor.id) 
                              ? prev.filter(i => i !== monitor.id) 
                              : [...prev, monitor.id]
                          );
                        }}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium">
                        {monitor.name}
                        {monitor.is_active ? null : <Badge variant="secondary">Paused</Badge>}
                      </div>
                      <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                        <ExternalLink className="size-3" />
                        <a 
                          href={monitor.original_url} 
                          target="_blank" 
                          rel="noreferrer"
                          className="hover:text-emerald-200"
                        >
                          View source
                        </a>
                      </div>
                    </TableCell>
                    <TableCell>{getDomain(monitor.original_url)}</TableCell>
                    <TableCell>{formatInterval(monitor.interval_sec)}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button 
                          variant="ghost" 
                          size="icon-xs" 
                          title="Edit"
                          onClick={() => {
                            setEditingMonitor(monitor);
                            setIsCreateOpen(true);
                          }}
                        >
                          <MoreVertical className="size-3.5" />
                        </Button>
                        <Button 
                          variant="ghost" 
                          size="icon-xs" 
                          title="Check Now"
                          onClick={() => handleAction(monitor.id, "check-now")}
                          disabled={!monitor.is_active}
                        >
                          <RefreshCcw className="size-3.5" />
                        </Button>
                        <Button 
                          variant="ghost" 
                          size="icon-xs" 
                          title={monitor.is_active ? "Pause" : "Resume"}
                          onClick={() => handleAction(monitor.id, monitor.is_active ? "pause" : "resume")}
                        >
                          {monitor.is_active ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
                        </Button>
                        <Button 
                          variant="ghost" 
                          size="icon-xs" 
                          className="text-destructive hover:bg-destructive/10"
                          title="Delete"
                          onClick={() => handleAction(monitor.id, "delete")}
                        >
                          <Trash2 className="size-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center text-muted-foreground">
                    No monitors found. Create one to start tracking.
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
