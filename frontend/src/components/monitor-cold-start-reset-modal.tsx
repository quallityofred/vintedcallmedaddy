"use client";

import { useState } from "react";
import { 
  AlertTriangle, 
  Loader2, 
  Trash2,
  RefreshCcw,
  History
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogHeader, 
  DialogTitle 
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { csrfFetch } from "@/lib/api-client";

interface MaintenanceResult {
  dry_run: boolean;
  monitor_id?: number;
  monitor_name?: string;
  would_delete_found_items?: number;
  deleted_found_items?: number;
  would_delete_seen_items?: number;
  deleted_seen_items?: number;
  pending_found_items_count?: number;
  warnings?: string[];
  [key: string]: unknown;
}

interface MonitorColdStartResetModalProps {
  monitorId: number;
  monitorName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function MonitorColdStartResetModal({ 
  monitorId, 
  monitorName, 
  open, 
  onOpenChange,
  onSuccess 
}: MonitorColdStartResetModalProps) {
  const [isPending, setIsPending] = useState(false);
  const [dryRunResult, setDryRunResult] = useState<MaintenanceResult | null>(null);
  const [confirmationInput, setConfirmationInput] = useState("");
  const [reason, setReason] = useState("");
  
  // Options
  const [clearFound, setClearFound] = useState(false);
  const [clearSeen, setClearSeen] = useState(true);

  const resetState = () => {
    setDryRunResult(null);
    setConfirmationInput("");
    setReason("");
  };

  const handleDryRun = async () => {
    setIsPending(true);
    try {
      const res = await csrfFetch(`/api/v1/maintenance/monitors/${monitorId}/reset-cold-start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          dry_run: true,
          clear_found_items: clearFound,
          clear_seen_items: clearSeen
        }),
      });
      const data = (await res.json()) as MaintenanceResult;
      setDryRunResult(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Dry run failed";
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  };

  const handleLive = async () => {
    if (!dryRunResult) return;
    
    setIsPending(true);
    try {
      const extra_confirm = [];
      if (clearSeen) extra_confirm.push("CLEAR_SEEN_ITEMS_NO_NOTIFY_BASELINE");
      if (clearFound) extra_confirm.push("CLEAR_FOUND_ITEMS_HISTORY");
      if (typeof dryRunResult.pending_found_items_count === "number" && dryRunResult.pending_found_items_count > 0) {
        extra_confirm.push("CLEAR_PENDING_FOUND_ITEMS_HISTORY_TOO");
      }

      const res = await csrfFetch(`/api/v1/maintenance/monitors/${monitorId}/reset-cold-start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          dry_run: false,
          reason: reason || `Reset monitor ${monitorId} via UI`,
          confirm: "RESET_MONITOR_COLD_START",
          extra_confirm,
          clear_found_items: clearFound,
          clear_seen_items: clearSeen
        }),
      });
      await res.json();
      toast.success("Monitor reset successful");
      onOpenChange(false);
      resetState();
      onSuccess?.();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Live reset failed";
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) resetState(); onOpenChange(o); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="h-5 w-5 text-primary" />
            Reset Cold Start: {monitorName}
          </DialogTitle>
          <DialogDescription>
            Resets last check time and optionally clears history.
          </DialogDescription>
        </DialogHeader>

        {!dryRunResult ? (
          <div className="space-y-4 py-4">
            <div className="flex items-center space-x-2">
              <Checkbox 
                id="reset-clear-seen" 
                checked={clearSeen} 
                onCheckedChange={(c) => setClearSeen(!!c)} 
              />
              <Label htmlFor="reset-clear-seen">Clear SeenItems baseline (no-notify next run)</Label>
            </div>
            <div className="flex items-center space-x-2">
              <Checkbox 
                id="reset-clear-found" 
                checked={clearFound} 
                onCheckedChange={(c) => setClearFound(!!c)} 
              />
              <Label htmlFor="reset-clear-found">Clear FoundItems history (reset items count)</Label>
            </div>
            <Button 
              className="w-full"
              variant="outline" 
              onClick={handleDryRun}
              disabled={isPending}
            >
              {isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCcw className="mr-2 h-4 w-4" />}
              Dry Run Reset
            </Button>
          </div>
        ) : (
          <div className="space-y-4 py-4">
            <div className="rounded-lg bg-muted p-3 text-sm space-y-1">
              <p>Monitor: <strong>{monitorName}</strong></p>
              {dryRunResult.would_delete_seen_items !== undefined && (
                <p>Would delete <strong>{dryRunResult.would_delete_seen_items}</strong> SeenItems.</p>
              )}
              {dryRunResult.would_delete_found_items !== undefined && (
                <p>Would delete <strong>{dryRunResult.would_delete_found_items}</strong> FoundItems.</p>
              )}
              {dryRunResult.pending_found_items_count !== undefined && dryRunResult.pending_found_items_count > 0 && (
                <p className="text-destructive font-bold">
                  Warning: {dryRunResult.pending_found_items_count} pending items will be lost!
                </p>
              )}
              <p>Last check time will be cleared.</p>
            </div>

            {dryRunResult.warnings && dryRunResult.warnings.length > 0 && (
              <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive border border-destructive/20">
                <p className="font-semibold flex items-center gap-1 mb-1">
                  <AlertTriangle className="h-4 w-4" />
                  Warnings:
                </p>
                <ul className="list-disc list-inside">
                  {dryRunResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}

            <div className="grid gap-2">
              <Label htmlFor="reset-reason">Reason</Label>
              <Input 
                id="reset-reason" 
                placeholder="e.g. Broken baseline or manual reset" 
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="reset-confirm">Type <strong>RESET_MONITOR_COLD_START</strong> to confirm</Label>
              <Input 
                id="reset-confirm" 
                placeholder="Confirmation string" 
                value={confirmationInput}
                onChange={(e) => setConfirmationInput(e.target.value)}
              />
            </div>

            <div className="flex gap-2">
              <Button variant="ghost" className="flex-1" onClick={() => setDryRunResult(null)} disabled={isPending}>Back</Button>
              <Button 
                variant="destructive" 
                className="flex-1"
                onClick={handleLive}
                disabled={isPending || !reason || confirmationInput !== "RESET_MONITOR_COLD_START"}
              >
                {isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                Execute Live Reset
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
