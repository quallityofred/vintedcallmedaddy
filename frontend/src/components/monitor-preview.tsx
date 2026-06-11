"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  Clock3,
  ExternalLink,
  History,
  Loader2,
  Pause,
  Pencil,
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
import { Checkbox } from "@/components/ui/checkbox";
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
import { DomainSelection } from "@/components/domain-selection";
import { MonitorDebugPanel } from "@/components/monitor-debug-panel";
import { MonitorTelegramTopicPanel } from "@/components/monitor-telegram-topic-panel";
import { MonitorColdStartResetModal } from "@/components/monitor-cold-start-reset-modal";
import { useAsyncActions } from "@/hooks/use-async-actions";
import { checkMonitorNow, csrfFetch } from "@/lib/api-client";
import { getMonitorTopicBatch, getTelegramTopicSettings, MonitorTopicStatus } from "@/lib/telegram-topics";
import { cn } from "@/lib/utils";

interface Monitor {
  id: number;
  name: string;
  original_url: string;
  interval_sec: number;
  is_active: boolean;
  last_check_at: string | null;
  items_found_count: number;
  domains: string[];
}

interface MonitorDraft {
  name: string;
  url: string;
  interval_sec: string;
  domains: string[];
}

const events = [
  { label: "DB-level dedup active", icon: ShieldCheck },
  { label: "Telegram delivery visible", icon: Bell },
  { label: "Adaptive intervals enabled", icon: Clock3 },
];

const emptyDraft: MonitorDraft = {
  name: "",
  url: "",
  interval_sec: "120",
  domains: [],
};

const MONITOR_POLL_INTERVAL_MS = 30_000;

function createDraftFromMonitor(monitor: Monitor): MonitorDraft {
  return {
    name: monitor.name,
    url: monitor.original_url,
    interval_sec: String(monitor.interval_sec),
    domains: Array.isArray(monitor.domains) ? monitor.domains : [],
  };
}

export function MonitorPreview() {
  const [monitors, setMonitors] = useState<Monitor[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [topicsEnabled, setTopicsEnabled] = useState(false);
  const [topicStatuses, setTopicStatuses] = useState<Record<number, MonitorTopicStatus>>({});
  const [editingMonitor, setEditingMonitor] = useState<Monitor | null>(null);
  const [resettingMonitor, setResettingMonitor] = useState<Monitor | null>(null);
  const [draft, setDraft] = useState<MonitorDraft>(emptyDraft);
  const monitorRequestId = useRef(0);
  const monitorMutationVersion = useRef(0);
  const { isPending, hasPending, runAction } = useAsyncActions();

  const fetchMonitors = useCallback(async (signal?: AbortSignal) => {
    const requestId = ++monitorRequestId.current;
    const startedMutationVersion = monitorMutationVersion.current;
    setError(false);
    try {
      const response = await fetch("/api/v1/monitors", {
        cache: "no-store",
        credentials: "same-origin",
        signal,
      });
      if (!response.ok) {
        throw new Error("Unable to load monitors");
      }
      const data = (await response.json()) as Monitor[];
      if (
        signal?.aborted ||
        requestId !== monitorRequestId.current ||
        startedMutationVersion !== monitorMutationVersion.current
      ) return;
      setMonitors(data);
      setSelectedIds((current) => current.filter((id) => data.some((monitor) => monitor.id === id)));
      setTopicStatuses((current) => {
        const validIds = new Set(data.map((monitor) => monitor.id));
        return Object.fromEntries(Object.entries(current).filter(([id]) => validIds.has(Number(id))));
      });
    } catch (err) {
      if (signal?.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
      setError(true);
    } finally {
      if (!signal?.aborted && requestId === monitorRequestId.current) {
        setLoading(false);
      }
    }
  }, []);

  const fetchTopicSettings = useCallback(async (signal?: AbortSignal) => {
    try {
      const settings = await getTelegramTopicSettings(signal);
      if (!signal?.aborted) {
        setTopicsEnabled(Boolean(settings.enabled ?? settings.telegram_topics_enabled));
      }
    } catch (err) {
      if (signal?.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
    }
  }, []);

  const fetchTopicStatuses = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await getMonitorTopicBatch(signal);
      if (signal?.aborted) return;
      setTopicsEnabled(Boolean(data.topics_enabled));
      setTopicStatuses(
        Object.fromEntries(
          Object.entries(data.topics).map(([monitorId, status]) => [Number(monitorId), status])
        )
      );
    } catch (err) {
      if (signal?.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      void fetchMonitors(controller.signal);
      void fetchTopicSettings(controller.signal);
      void fetchTopicStatuses(controller.signal);
    });

    const handleVisibilityChange = () => {
        if (document.visibilityState === "visible") {
          void fetchMonitors();
        }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    const interval = setInterval(() => {
        if (document.visibilityState === "visible") void fetchMonitors();
    }, MONITOR_POLL_INTERVAL_MS);

    return () => {
        controller.abort();
        clearInterval(interval);
        document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [fetchMonitors, fetchTopicSettings, fetchTopicStatuses]);

  const updateTopicStatus = useCallback((monitorId: number, status: MonitorTopicStatus | null) => {
    setTopicStatuses((current) => {
      if (!status) {
        const next = { ...current };
        delete next[monitorId];
        return next;
      }
      return { ...current, [monitorId]: status };
    });
  }, []);

  const upsertMonitor = useCallback((updated: Monitor) => {
    monitorMutationVersion.current += 1;
    setMonitors((current) => {
      if (!current) return [updated];
      const exists = current.some((monitor) => monitor.id === updated.id);
      if (!exists) return [updated, ...current];
      return current.map((monitor) => (monitor.id === updated.id ? updated : monitor));
    });
  }, []);

  const removeMonitors = useCallback((ids: number[]) => {
    const idSet = new Set(ids);
    monitorMutationVersion.current += 1;
    setMonitors((current) => (current ? current.filter((monitor) => !idSet.has(monitor.id)) : current));
    setSelectedIds((current) => current.filter((id) => !idSet.has(id)));
    setTopicStatuses((current) => {
      const next = { ...current };
      for (const id of idSet) {
        delete next[id];
      }
      return next;
    });
  }, []);


  const openCreateDialog = () => {
    setEditingMonitor(null);
    setDraft(emptyDraft);
    setIsCreateOpen(true);
  };

  const openEditDialog = (monitor: Monitor) => {
    setEditingMonitor(monitor);
    setDraft(createDraftFromMonitor(monitor));
    setIsCreateOpen(true);
  };

  const closeEditor = () => {
    setIsCreateOpen(false);
    setEditingMonitor(null);
    setDraft(emptyDraft);
  };

  const handleAction = async (id: number, action: "check-now" | "pause" | "resume" | "delete") => {
    const nextActionKey = `monitor:${id}:${action}`;
    await runAction(nextActionKey, async () => {
      if (action === "check-now") {
        await checkMonitorNow(id);
        toast.success("Monitor check queued");
        void fetchMonitors();
        return;
      }
      const isDelete = action === "delete";
      const response = await csrfFetch(isDelete ? `/api/v1/monitors/${id}` : `/api/v1/monitors/${id}/${action}`, {
        method: isDelete ? "DELETE" : "POST",
      });

      const message = `Monitor ${isDelete ? "deleted" : "updated"}`;

      toast.success(message);
      if (isDelete) {
        removeMonitors([id]);
        return;
      }
      const updated = (await response.json()) as Monitor;
      upsertMonitor(updated);
    }).catch(async (err) => {
      const message = err instanceof Error ? err.message : "Monitor action failed";
      toast.error(message);
    });
  };

  const handleBulkDelete = async () => {
    if (selectedIds.length === 0) return;
    if (!confirm(`Delete ${selectedIds.length} selected monitor${selectedIds.length === 1 ? "" : "s"}?`)) return;

    await runAction("monitors:bulk-delete", async () => {
      const response = await csrfFetch("/api/v1/monitors/bulk-delete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ monitor_ids: selectedIds }),
      });

      const { deleted_count } = (await response.json()) as { deleted_count: number };
      toast.success(`${deleted_count} monitor${deleted_count === 1 ? "" : "s"} deleted`);
      removeMonitors(selectedIds);
    }).catch(() => {
      toast.error("Bulk delete failed");
    });
  };

  const handleBulkState = async (action: "pause" | "resume") => {
    const activeCount = monitors?.filter((m) => m.is_active).length || 0;
    const pausedCount = (monitors?.length || 0) - activeCount;

    const confirmationMessage =
      action === "pause"
        ? `Disable all ${activeCount} currently enabled monitors? This will stop new checks until re-enabled.`
        : `Enable all ${pausedCount} currently disabled monitors?`;

    if (!confirm(confirmationMessage)) return;

    await runAction(`monitors:bulk-${action}`, async () => {
      const response = await csrfFetch("/api/v1/monitors/bulk-state", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action, dry_run: false }),
      });

      const result = (await response.json()) as { changed_count: number };
      toast.success(`${action === "pause" ? "Paused" : "Resumed"} ${result.changed_count} monitors`);
      void fetchMonitors();
    }).catch((err) => {
      const message = err instanceof Error ? err.message : `Bulk ${action} failed`;
      toast.error(message);
    });
  };

  const handleCreateOrUpdate = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (draft.domains.length === 0) {
      toast.error("Please select at least one domain");
      return;
    }
    const interval = Number.parseInt(draft.interval_sec, 10);
    const payload = {
      name: draft.name,
      url: draft.url,
      interval_sec: interval,
      domains: draft.domains,
    };

    const submitKey = editingMonitor ? `monitor:${editingMonitor.id}:save` : "monitor:create";
    await runAction(submitKey, async () => {
      const method = editingMonitor ? "PATCH" : "POST";
      const path = editingMonitor ? `/api/v1/monitors/${editingMonitor.id}` : "/api/v1/monitors";

      const response = await csrfFetch(path, {
        method,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const data = (await response.json()) as Monitor;
      const wasNormalized = data.original_url !== payload.url;

      toast.success(`Monitor ${editingMonitor ? "updated" : "created"}${wasNormalized ? " (URL cleaned)" : ""}`);
      upsertMonitor(data);
      closeEditor();
    }).catch((err) => {
      const message = err instanceof Error ? err.message : `Failed to ${editingMonitor ? "update" : "create"} monitor`;
      toast.error(message);
    });
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

  const formatLastCheck = (value: string | null) => {
    if (!value) return "Not checked yet";
    try {
      return new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value));
    } catch {
      return "Unknown";
    }
  };

  const formatDomain = (domain: string) => domain.replace(/^www\./, "");

  const formatMonitorDomains = (monitor: Monitor) => {
    const domains = monitor.domains?.length ? monitor.domains : [getDomain(monitor.original_url)];
    const displayDomains = domains.map(formatDomain);

    return {
      label: displayDomains.join(", "),
      title: displayDomains.join(", "),
    };
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
  const isSubmitting = isPending(editingMonitor ? `monitor:${editingMonitor.id}:save` : "monitor:create");
  const bulkDeleting = isPending("monitors:bulk-delete");
  const bulkPausing = isPending("monitors:bulk-pause");
  const bulkResuming = isPending("monitors:bulk-resume");
  const bulkBusy = bulkDeleting || bulkPausing || bulkResuming;

  const activeCount = monitors?.filter((m) => m.is_active).length || 0;
  const pausedCount = (monitors?.length || 0) - activeCount;

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
            <Dialog
              open={isCreateOpen}
              onOpenChange={(open) => {
                if (open) {
                  setIsCreateOpen(true);
                } else {
                  closeEditor();
                }
              }}
            >
              <DialogTrigger
                render={
                  <Button className="w-full sm:w-auto" onClick={openCreateDialog} size="sm">
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
                        onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                        placeholder="Nike Dunk Low 42"
                        required
                        value={draft.name}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="url">Vinted URL</Label>
                      <Input
                        disabled={isSubmitting}
                        id="url"
                        name="url"
                        onChange={(event) => setDraft((current) => ({ ...current, url: event.target.value }))}
                        placeholder="https://www.vinted.fr/catalog?..."
                        required
                        value={draft.url}
                      />
                      <p className="text-[10px] text-muted-foreground">
                        URL will be cleaned and forced to Newest first.
                      </p>
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="interval_sec">Check interval in seconds</Label>
                      <Input
                        disabled={isSubmitting}
                        id="interval_sec"
                        name="interval_sec"
                        type="number"
                        min="60"
                        max="3600"
                        onChange={(event) => setDraft((current) => ({ ...current, interval_sec: event.target.value }))}
                        required
                        value={draft.interval_sec}
                      />
                    </div>
                    <DomainSelection
                      selectedDomains={draft.domains}
                      onSelectionChange={(domains) => setDraft((current) => ({ ...current, domains }))}
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
          <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-emerald-200/25 bg-emerald-300/[0.04] p-8 text-center sm:p-12">
            <div className="mb-4 flex size-12 items-center justify-center rounded-2xl border border-emerald-200/20 bg-emerald-300/10 text-emerald-100">
              <Radar className="size-5" />
            </div>
            <p className="text-lg font-semibold">No monitors yet</p>
            <p className="mt-2 max-w-sm text-sm leading-6 text-muted-foreground">
              Create your first Vinted search monitor, choose target domains, and let the scheduler handle checks.
            </p>
            <Button
              className="mt-6"
              onClick={openCreateDialog}
              size="sm"
            >
              <Plus className="size-3.5" />
              New monitor
            </Button>
          </div>
        ) : (
          <div className="grid gap-3">
            <div className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-black/15 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <Checkbox
                  aria-label="Select all monitors"
                  checked={allSelected}
                  className="size-5 rounded-md border-emerald-200/45 bg-black/30"
                  disabled={!monitors?.length || loading}
                  onCheckedChange={toggleAll}
                />
                <button
                  className="text-left text-sm font-medium text-foreground transition hover:text-emerald-100"
                  onClick={toggleAll}
                  type="button"
                >
                  Select all monitors
                </button>
              </div>
              {hasSelection ? (
                <Button
                  aria-label={`Delete ${selectedIds.length} selected monitors`}
                  className="h-8 text-[11px]"
                  disabled={bulkBusy}
                  onClick={handleBulkDelete}
                  size="sm"
                  variant="destructive"
                >
                  {bulkDeleting ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                  Delete selected ({selectedIds.length})
                </Button>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    disabled={activeCount === 0 || bulkBusy}
                    onClick={() => handleBulkState("pause")}
                    size="sm"
                    variant="outline"
                    className="h-8 text-[11px]"
                  >
                    {bulkPausing ? <Loader2 className="size-3 animate-spin" /> : <Pause className="size-3" />}
                    Disable all enabled ({activeCount})
                  </Button>
                  <Button
                    disabled={pausedCount === 0 || bulkBusy}
                    onClick={() => handleBulkState("resume")}
                    size="sm"
                    variant="outline"
                    className="h-8 text-[11px]"
                  >
                    {bulkResuming ? <Loader2 className="size-3 animate-spin" /> : <Play className="size-3" />}
                    Enable all paused ({pausedCount})
                  </Button>
                  <p className="ml-2 text-xs text-muted-foreground">{monitors?.length || 0} monitors</p>
                </div>
              )}
            </div>

            <div className="grid gap-3">
              {monitors.map((monitor) => {
                const checkKey = `monitor:${monitor.id}:check-now`;
                const pauseKey = `monitor:${monitor.id}:pause`;
                const resumeKey = `monitor:${monitor.id}:resume`;
                const deleteKey = `monitor:${monitor.id}:delete`;
                const monitorBusy = hasPending(`monitor:${monitor.id}:`);
                const isSelected = selectedIds.includes(monitor.id);
                const domainSummary = formatMonitorDomains(monitor);

                return (
                  <article
                    key={monitor.id}
                    className={cn(
                      "rounded-3xl border p-4 transition-all sm:p-5",
                      isSelected
                        ? "border-emerald-300/55 bg-emerald-300/[0.08] shadow-xl shadow-emerald-950/20"
                        : "border-white/10 bg-white/[0.035] hover:border-emerald-200/30 hover:bg-white/[0.055]",
                      monitor.is_active ? "" : "opacity-80"
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <Checkbox
                        aria-label={`Select monitor ${monitor.name}`}
                        checked={isSelected}
                        className="mt-1 size-5 rounded-md border-emerald-200/45 bg-black/30"
                        onCheckedChange={() => toggleMonitor(monitor.id)}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="max-w-full truncate text-base font-semibold tracking-tight">
                                {monitor.name}
                              </h3>
                              <Badge
                                className={cn(
                                  "rounded-full border px-2 py-0.5 text-[11px]",
                                  monitor.is_active
                                    ? "border-emerald-200/25 bg-emerald-300/10 text-emerald-100"
                                    : "border-amber-200/25 bg-amber-300/10 text-amber-100"
                                )}
                                variant="secondary"
                              >
                                {monitor.is_active ? "Active" : "Paused"}
                              </Badge>
                            </div>
                            <a
                              aria-label={`Open source search for ${monitor.name}`}
                              className="mt-2 inline-flex max-w-full items-center gap-1.5 truncate rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-xs text-muted-foreground transition hover:border-emerald-200/35 hover:text-emerald-100"
                              href={monitor.original_url}
                              rel="noreferrer"
                              target="_blank"
                            >
                              <ExternalLink className="size-3 shrink-0" />
                              <span className="truncate">Open source URL</span>
                            </a>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button
                              aria-label={`Edit monitor ${monitor.name}`}
                              disabled={monitorBusy || bulkDeleting}
                              onClick={() => openEditDialog(monitor)}
                              size="sm"
                              title="Edit monitor"
                              variant="secondary"
                            >
                              <Pencil className="size-3.5" />
                              Edit
                            </Button>
                            <Button
                              aria-label={`Run monitor check for ${monitor.name}`}
                              disabled={!monitor.is_active || monitorBusy || bulkDeleting}
                              onClick={() => handleAction(monitor.id, "check-now")}
                              size="sm"
                              title="Check now"
                              variant="outline"
                            >
                              {isPending(checkKey) ? (
                                <Loader2 className="size-3.5 animate-spin" />
                              ) : (
                                <RefreshCcw className="size-3.5" />
                              )}
                              Check
                            </Button>
                            <MonitorDebugPanel monitorId={monitor.id} name={monitor.name} />
                            <MonitorTelegramTopicPanel
                              monitorId={monitor.id}
                              topicsEnabled={topicsEnabled}
                              status={topicStatuses[monitor.id] ?? null}
                              onStatusChange={updateTopicStatus}
                            />
                            <Button
                              aria-label={`Reset cold start for ${monitor.name}`}
                              disabled={monitorBusy || bulkDeleting}
                              onClick={() => setResettingMonitor(monitor)}
                              size="sm"
                              title="Reset cold start"
                              variant="outline"
                            >
                              <History className="size-3.5" />
                              Reset
                            </Button>
                            <Button
                              aria-label={`${monitor.is_active ? "Pause" : "Resume"} monitor ${monitor.name}`}
                              disabled={monitorBusy || bulkDeleting}
                              onClick={() => handleAction(monitor.id, monitor.is_active ? "pause" : "resume")}
                              size="sm"
                              title={monitor.is_active ? "Pause monitor" : "Resume monitor"}
                              variant="outline"
                            >
                              {isPending(pauseKey) || isPending(resumeKey) ? (
                                <Loader2 className="size-3.5 animate-spin" />
                              ) : monitor.is_active ? (
                                <Pause className="size-3.5" />
                              ) : (
                                <Play className="size-3.5" />
                              )}
                              {monitor.is_active ? "Pause" : "Resume"}
                            </Button>
                            <Button
                              aria-label={`Delete monitor ${monitor.name}`}
                              disabled={monitorBusy || bulkDeleting}
                              onClick={() => handleAction(monitor.id, "delete")}
                              size="sm"
                              title="Delete monitor"
                              variant="destructive"
                            >
                              {isPending(deleteKey) ? (
                                <Loader2 className="size-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="size-3.5" />
                              )}
                              Delete
                            </Button>
                          </div>
                        </div>

                        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                          <div className="rounded-2xl border border-white/10 bg-black/15 p-3">
                            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                              Domains
                            </p>
                            <p className="mt-1 truncate text-sm font-medium" title={domainSummary.title}>
                              {domainSummary.label}
                            </p>
                          </div>
                          <div className="rounded-2xl border border-white/10 bg-black/15 p-3">
                            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                              Interval
                            </p>
                            <p className="mt-1 text-sm font-medium tabular-nums">{formatInterval(monitor.interval_sec)}</p>
                          </div>
                          <div className="rounded-2xl border border-white/10 bg-black/15 p-3">
                            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                              Found
                            </p>
                            <p className="mt-1 text-sm font-medium tabular-nums">
                              {monitor.items_found_count} item{monitor.items_found_count === 1 ? "" : "s"}
                            </p>
                          </div>
                          <div className="rounded-2xl border border-white/10 bg-black/15 p-3">
                            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                              Last check
                            </p>
                            <p className="mt-1 truncate text-sm font-medium">{formatLastCheck(monitor.last_check_at)}</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        )}
        <div className="mt-6 grid gap-3 sm:mt-8 sm:grid-cols-3 xl:grid-cols-1">
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

      <MonitorColdStartResetModal
        monitorId={resettingMonitor?.id ?? 0}
        monitorName={resettingMonitor?.name ?? ""}
        open={!!resettingMonitor}
        onOpenChange={(open) => !open && setResettingMonitor(null)}
        onSuccess={fetchMonitors}
      />
    </Card>
  );
}
