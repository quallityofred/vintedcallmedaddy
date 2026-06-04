import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Info, Loader2 } from "lucide-react";
import { useState, useEffect } from "react";

interface DebugData {
  explanation: string;
  last_check_started_at: string | null;
  last_check_completed_at: string | null;
  scheduler: { job_exists: boolean; next_run_time: string | null; job_id?: string };
  last_error: string | null;
  cf_worker?: { mode: string; configured: boolean; url_masked: string | null };
}

export function MonitorDebugPanel({ monitorId, name }: { monitorId: number, name: string }) {
  const [data, setData] = useState<DebugData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }

    const controller = new AbortController();
    const { signal } = controller;

    const fetchDebug = async (isInitial = false) => {
      if (isInitial) setLoading(true);
      try {
        const response = await fetch(`/api/v1/monitors/${monitorId}/debug`, { signal });
        if (!response.ok) {
          const errData = (await response.json().catch(() => ({}))) as { detail?: string };
          throw new Error(errData.detail || "Failed to load debug data");
        }
        const result = (await response.json()) as DebugData;
        setData(result);
        setError(null);
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return;
        const message = err instanceof Error ? err.message : "Could not load debug info.";
        setError(message);
      } finally {
        if (isInitial) setLoading(false);
      }
    };

    fetchDebug(true);
    const interval = setInterval(() => fetchDebug(false), 3000);

    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [open, monitorId]);

  const handleOpenChange = (newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      setData(null);
      setError(null);
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button variant="ghost" size="icon-xs" title="Debug status" />}>
        <Info className="size-3.5" />
        <span className="sr-only">Debug status</span>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Monitor Status: {name}</DialogTitle>
          <DialogDescription>Diagnostic information for monitor checks.</DialogDescription>
        </DialogHeader>
        {loading && !data && <div className="py-4 text-center"><Loader2 className="mx-auto size-5 animate-spin" /></div>}
        {error && !data && <div className="py-4 text-center text-sm text-red-400">{error}</div>}
        {data && (
          <div className="grid gap-4 py-4 text-sm">
            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
              <p className="font-medium text-emerald-200">Execution Status</p>
              <p className="mt-1 text-muted-foreground">{data.explanation}</p>
            </div>
            
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div><p className="text-muted-foreground">Started</p><p>{data.last_check_started_at ? new Date(data.last_check_started_at).toLocaleString() : 'N/A'}</p></div>
              <div><p className="text-muted-foreground">Completed</p><p>{data.last_check_completed_at ? new Date(data.last_check_completed_at).toLocaleString() : 'N/A'}</p></div>
            </div>

            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
               <p className="font-medium text-emerald-200">Scheduler Job</p>
               <p className="mt-1 text-muted-foreground">{data.scheduler.job_exists ? `Active (Next run: ${data.scheduler.next_run_time ? new Date(data.scheduler.next_run_time).toLocaleString() : 'unknown'})` : 'No active job'}</p>
            </div>

            <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
               <p className="font-medium text-emerald-200">Cloudflare Worker</p>
               <p className="mt-1 text-sm text-muted-foreground">Mode: {data.cf_worker?.mode || 'auto'}</p>
               <p className="text-sm text-muted-foreground">Configured: {data.cf_worker?.configured ? 'Yes' : 'No'}</p>
               {data.cf_worker?.url_masked && <p className="text-xs text-muted-foreground mt-1">URL: {data.cf_worker.url_masked}</p>}
            </div>

            {data.last_error && (
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-red-200">
                <p className="font-medium">Last Error</p>
                <p className="mt-1 text-xs">{data.last_error}</p>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
