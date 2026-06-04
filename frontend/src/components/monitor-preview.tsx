"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Bell,
  Clock3,
  ExternalLink,
  Loader2,
  MoreVertical,
  Pause,
  Play,
  Plus,
  Radar,
  RefreshCcw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DomainSelection } from "@/components/domain-selection";

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
  { label: "Telegram delivery visible", icon: Bell },
  { label: "Adaptive intervals enabled", icon: Clock3 },
];

export function MonitorPreview() {
  const [monitors, setMonitors] = useState<Monitor[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [actionKey, setActionKey] = useState<string | null>(null);
  const [editingMonitor, setEditingMonitor] = useState<Monitor | null>(null);
  const [selectedDomains, setSelectedDomains] = useState<string[]>([]);

  const fetchMonitors = useCallback(async () => {
    setError(false);
    try {
      const response = await fetch("/api/v1/monitors", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error("Unable to load monitors");
      }
      const data = (await response.json()) as Monitor[];
      setMonitors(data);
      setSelectedIds((current) => current.filter((id) => data.some((monitor) => monitor.id === id)));
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
    const response = await fetch("/api/v1/auth/csrf", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const { csrf_token } = (await response.json()) as { csrf_token: string };
    return csrf_token;
  };

  const handleAction = async (id: number, action: "check-now" | "pause" | "resume" | "delete") => {
    const nextActionKey = `${id}:${action}`;
    setActionKey(nextActionKey);

    try {
      const csrfToken = await getCsrfToken();
      const isDelete = action === "delete";
      const response = await fetch(isDelete ? `/api/v1/monitors/${id}` : `/api/v1/monitors/${id}/${action}`, {
        method: isDelete ? "DELETE" : "POST",
        credentials: "same-origin",
        headers: {
          "X-CSRF-Token": csrfToken,
        },
      });

      if (!response.ok) throw new Error("Action failed");

      const message = action === "check-now" ? "Monitor check queued" : `Monitor ${isDelete ? "deleted" : "updated"}`;
      toast.success(message);
      void fetchMonitors();
    } catch {
      toast.error("Monitor action failed");
    } finally {
      setActionKey(null);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedIds.length === 0) return;
    if (!confirm(`Delete ${selectedIds.length} selected monitor${selectedIds.length === 1 ? "" : "s"}?`)) return;

    setBulkDeleting(true);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/monitors/bulk-delete", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ monitor_ids: selectedIds }),
      });

      if (!response.ok) throw new Error("Bulk delete failed");

      const { deleted_count } = (await response.json()) as { deleted_count: number };
      toast.success(`${deleted_count} monitor${deleted_count === 1 ? "" : "s"} deleted`);
      setSelectedIds([]);
      void fetchMonitors();
    } catch {
      toast.error("Bulk delete failed");
    } finally {
      setBulkDeleting(false);
    }
  };

  const handleCreateOrUpdate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (selectedDomains.length === 0) {
      toast.error("Please select at least one domain");
      return;
    }
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    const payload = {
      name: formData.get("name") as string,
      url: formData.get("url") as string,
      interval_sec: parseInt(formData.get("interval_sec") as string),
      domains: selectedDomains,
    };

    try {
      const csrfToken = await getCsrfToken();
      const method = editingMonitor ? "PATCH" : "POST";
      const path = editingMonitor ? `/api/v1/monitors/${editingMonitor.id}` : "/api/v1/monitors";

      const response = await fetch(path, {
        method,
        credentials: "same-origin",
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

      toast.success(`Monitor ${editingMonitor ? "updated" : "created"}`);
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
      const parsed = new URL(url);
      return parsed.hostname.replace("www.", "");
    } catch {
      return "unknown";
    }
  };

  const formatInterval = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m${seconds % 60}s`;
  };

  const allSelected = Boolean(monitors?.length && selectedIds.length === monitors.length);
  const hasSelection = selectedIds.length > 0;

  const toggleAll = () => {
    if (!monitors) return;
    setSelectedIds(allSelected ? [] : monitors.map((monitor) => monitor.id));
  };

  const toggleMonitor = (id: number) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  const hasMonitors = monitors && monitors.length > 0;

  return (
    <Card className="glass-panel min-w-0 overflow-hidden">
      <CardHeader className="border-b border-white/10 p-4 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2">
              <Radar className="size-4 text-emerald-200" />
              Monitors
            </CardTitle>
            <CardDescription>Manage search URLs, check cadence, and monitor controls.</CardDescription>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            {hasSelection && hasMonitors ? (
              <Button
                aria-label={`Delete ${selectedIds.length} selected monitors`}
                className="w-full animate-in fade-in slide-in-from-right-2 sm:w-auto"
                disabled={bulkDeleting}
                onClick={handleBulkDelete}
                size="sm"
                variant="destructive"
              >
                {bulkDeleting ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                Delete selected ({selectedIds.length})
              </Button>
            ) : null}

            <Dialog
              open={isCreateOpen}
              onOpenChange={(open) => {
                setIsCreateOpen(open);
                if (!open) {
                    setEditingMonitor(null);
                    setSelectedDomains([]);
                }
              }}
            >
              <DialogTrigger
                render={
                  <Button className="w-full sm:w-auto" size="sm">
                    <Plus className="size-3.5" />
                    New monitor
                  </Button>
                }
              />
              <DialogContent className="sm:max-w-[440px]">
                <form onSubmit={handleCreateOrUpdate}>
                  <DialogHeader>
                    <DialogTitle>{editingMonitor ? "Edit monitor" : "Create monitor"}</DialogTitle>
                    <DialogDescription>
                      {editingMonitor
                        ? "Update this monitor without changing ownership or notification safety."
                        : "Add a Vinted search URL and choose how often it should be checked."}
                    </DialogDescription>
                  </DialogHeader>
                  <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                      <Label htmlFor="name">Name</Label>
                      <Input
                        disabled={isSubmitting}
                        id="name"
                        name="name"
                        defaultValue={editingMonitor?.name}
                        placeholder="Nike Dunk Low 42"
                        required
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="url">Vinted URL</Label>
                      <Input
                        disabled={isSubmitting}
                        id="url"
                        name="url"
                        defaultValue={editingMonitor?.original_url}
                        placeholder="https://www.vinted.fr/catalog?..."
                        required
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="interval_sec">Check interval in seconds</Label>
                      <Input
                        disabled={isSubmitting}
                        id="interval_sec"
                        name="interval_sec"
                        type="number"
                        defaultValue={editingMonitor?.interval_sec || "120"}
                        min="60"
                        max="3600"
                        required
                      />
                    </div>
                    <DomainSelection
                      selectedDomains={selectedDomains}
                      onSelectionChange={setSelectedDomains}
                    />
                  </div>
                  <DialogFooter>
                    <Button className="w-full sm:w-auto" type="submit" disabled={isSubmitting}>
                      {isSubmitting ? (
                        <>
                          <Loader2 className="size-4 animate-spin" />
                          {editingMonitor ? "Updating" : "Creating"}
                        </>
                      ) : editingMonitor ? (
                        "Update monitor"
                      ) : (
                        "Create monitor"
                      )}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </div>
      </CardHeader>
      <CardContent className="min-w-0 p-3 sm:p-5">
        {loading ? (
            <div className="flex h-36 items-center justify-center rounded-2xl border border-white/10 bg-black/10">
                <Loader2 className="size-5 animate-spin text-emerald-200" />
            </div>
        ) : error ? (
            <div className="flex h-36 items-center justify-center rounded-2xl border border-red-300/20 bg-red-400/10 text-center text-sm text-red-100">
              Monitors could not be loaded. Refresh the page or try again later.
            </div>
        ) : !hasMonitors ? (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-white/10 bg-black/10 p-12 text-center">
            <p className="text-lg font-medium">No monitors yet</p>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">Create your first Vinted search monitor to start tracking new items.</p>
            <Button
              className="mt-6"
              onClick={() => setIsCreateOpen(true)}
              size="sm"
            >
              <Plus className="size-3.5" />
              New monitor
            </Button>
          </div>
        ) : (
          <div className="min-w-0 overflow-hidden rounded-2xl border border-white/10 bg-black/10">
          <div className="max-w-full overflow-x-auto">
                    <Table className="min-w-[760px]">
                        <TableHeader>
                            <TableRow>
                                <TableHead className="w-10">
                                    <input
                                        aria-label="Select all monitors"
                                        checked={allSelected}
                                        className="size-4 rounded border-white/20 bg-white/5 accent-emerald-500"
                                        disabled={!monitors?.length || loading}
                                        onChange={toggleAll}
                                        type="checkbox"
                                    />
                                </TableHead>
                                <TableHead>Search</TableHead>
                                <TableHead>Domain</TableHead>
                                <TableHead className="text-right">Interval</TableHead>
                                <TableHead className="text-right">Actions</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {monitors.map((monitor) => {
                                const checkKey = `${monitor.id}:check-now`;
                                const pauseKey = `${monitor.id}:pause`;
                                const resumeKey = `${monitor.id}:resume`;
                                const deleteKey = `${monitor.id}:delete`;

                                return (
                                <TableRow key={monitor.id} className={!monitor.is_active ? "opacity-70" : ""}>
                                    <TableCell>
                                    <input
                                        aria-label={`Select monitor ${monitor.name}`}
                                        checked={selectedIds.includes(monitor.id)}
                                        className="size-4 rounded border-white/20 bg-white/5 accent-emerald-500"
                                        onChange={() => toggleMonitor(monitor.id)}
                                        type="checkbox"
                                    />
                                    </TableCell>
                                    <TableCell className="max-w-[18rem]">
                                    <div className="flex min-w-0 items-center gap-2 font-medium">
                                        <span className="truncate">{monitor.name}</span>
                                        {monitor.is_active ? null : <Badge variant="secondary">Paused</Badge>}
                                    </div>
                                    <a
                                        aria-label={`Open source search for ${monitor.name}`}
                                        className="mt-1 inline-flex max-w-full items-center gap-1 truncate text-xs text-muted-foreground hover:text-emerald-200"
                                        href={monitor.original_url}
                                        rel="noreferrer"
                                        target="_blank"
                                    >
                                        <ExternalLink className="size-3 shrink-0" />
                                        <span className="truncate">Open source URL</span>
                                    </a>
                                    </TableCell>
                                    <TableCell className="text-muted-foreground">{getDomain(monitor.original_url)}</TableCell>
                                    <TableCell className="text-right tabular-nums">{formatInterval(monitor.interval_sec)}</TableCell>
                                    <TableCell>
                                    <div className="flex justify-end gap-1">
                                        <Button
                                        aria-label={`Edit monitor ${monitor.name}`}
                                        onClick={() => {
                                            setEditingMonitor(monitor);
                                            setIsCreateOpen(true);
                                        }}
                                        size="icon-xs"
                                        title="Edit"
                                        variant="ghost"
                                        >
                                        <MoreVertical className="size-3.5" />
                                        </Button>
                                        <Button
                                        aria-label={`Run monitor check for ${monitor.name}`}
                                        disabled={!monitor.is_active || actionKey === checkKey}
                                        onClick={() => handleAction(monitor.id, "check-now")}
                                        size="icon-xs"
                                        title="Check now"
                                        variant="ghost"
                                        >
                                        {actionKey === checkKey ? (
                                            <Loader2 className="size-3.5 animate-spin" />
                                        ) : (
                                            <RefreshCcw className="size-3.5" />
                                        )}
                                        </Button>
                                        <Button
                                        aria-label={`${monitor.is_active ? "Pause" : "Resume"} monitor ${monitor.name}`}
                                        disabled={actionKey === pauseKey || actionKey === resumeKey}
                                        onClick={() => handleAction(monitor.id, monitor.is_active ? "pause" : "resume")}
                                        size="icon-xs"
                                        title={monitor.is_active ? "Pause" : "Resume"}
                                        variant="ghost"
                                        >
                                        {actionKey === pauseKey || actionKey === resumeKey ? (
                                            <Loader2 className="size-3.5 animate-spin" />
                                        ) : monitor.is_active ? (
                                            <Pause className="size-3.5" />
                                        ) : (
                                            <Play className="size-3.5" />
                                        )}
                                        </Button>
                                        <Button
                                        aria-label={`Delete monitor ${monitor.name}`}
                                        className="text-destructive hover:bg-destructive/10"
                                        disabled={actionKey === deleteKey}
                                        onClick={() => handleAction(monitor.id, "delete")}
                                        size="icon-xs"
                                        title="Delete"
                                        variant="ghost"
                                        >
                                        {actionKey === deleteKey ? (
                                            <Loader2 className="size-3.5 animate-spin" />
                                        ) : (
                                            <Trash2 className="size-3.5" />
                                        )}
                                        </Button>
                                    </div>
                                    </TableCell>
                                </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </div>
            </div>
        )}
        <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
          {events.map((event) => (
            <div key={event.label} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <div className="mb-3 flex size-9 items-center justify-center rounded-xl bg-emerald-300/10 text-emerald-200">
                <event.icon className="size-4" />
              </div>
              <p className="text-sm font-medium">{event.label}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Current controls preserve backend ownership, deduplication, and notification safety.
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
