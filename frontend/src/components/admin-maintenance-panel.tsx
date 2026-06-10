"use client";

import { useState } from "react";
import { 
  AlertTriangle, 
  CheckCircle2, 
  History, 
  Loader2, 
  RefreshCcw, 
  ShieldAlert, 
  Trash2,
  Radar
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogFooter, 
  DialogHeader, 
  DialogTitle 
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { csrfFetch } from "@/lib/api-client";

interface Monitor {
  id: number;
  name: string;
  is_active: boolean;
}

interface MaintenanceResult {
  dry_run: boolean;
  would_delete_found_items?: number;
  deleted_found_items?: number;
  would_delete_seen_items?: number;
  deleted_seen_items?: number;
  would_mark_notified_count?: number;
  pending_found_items_count?: number;
  inactive_monitors_count?: number;
  warnings?: string[];
  [key: string]: unknown;
}

interface MaintenanceBody {
  dry_run: boolean;
  reason?: string;
  confirm?: string;
  extra_confirm?: string[];
  include_found_items?: boolean;
  found_items_retention_days?: number;
  clear_found_items?: boolean;
  clear_seen_items?: boolean;
}

export function AdminMaintenancePanel() {
  const [isPending, setIsPending] = useState(false);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [dryRunResult, setDryRunResult] = useState<MaintenanceResult | null>(null);
  const [confirmationInput, setConfirmationInput] = useState("");
  const [reason, setReason] = useState("");
  
  // Options
  const [clearFound, setClearFound] = useState(false);
  const [retentionDays, setRetentionDays] = useState(30);

  const resetModals = () => {
    setActiveAction(null);
    setDryRunResult(null);
    setConfirmationInput("");
    setReason("");
  };

  const handleDryRun = async (action: string) => {
    setIsPending(true);
    setActiveAction(action);
    try {
      if (action === "reset_inactive") {
        const res = await fetch("/api/v1/monitors");
        const monitors = (await res.json()) as Monitor[];
        const inactive = monitors.filter(m => !m.is_active);
        
        setDryRunResult({
          dry_run: true,
          inactive_monitors_count: inactive.length,
          warnings: ["This will reset ALL inactive monitors. This action is irreversible."]
        });
        return;
      }

      let endpoint = "";
      const body: MaintenanceBody = { dry_run: true };

      if (action === "retention") {
        endpoint = "/api/v1/maintenance/history-retention/cleanup";
        body.include_found_items = clearFound;
        body.found_items_retention_days = retentionDays;
      } else if (action === "pending_ack") {
        endpoint = "/api/v1/maintenance/pending-notifications/ack-no-notify";
      }

      const res = await csrfFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await res.json()) as MaintenanceResult;
      setDryRunResult(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Dry run failed";
      toast.error(message);
      resetModals();
    } finally {
      setIsPending(false);
    }
  };

  const handleLive = async () => {
    if (!activeAction || !dryRunResult) return;
    
    setIsPending(true);
    try {
      if (activeAction === "reset_inactive") {
        if (confirmationInput !== "RESET_ALL_INACTIVE_MONITORS") throw new Error("Invalid confirmation string");
        
        const resMon = await fetch("/api/v1/monitors");
        const monitors = (await resMon.json()) as Monitor[];
        const inactive = monitors.filter(m => !m.is_active);
        
        let successCount = 0;
        for (const monitor of inactive) {
          try {
            await csrfFetch(`/api/v1/maintenance/monitors/${monitor.id}/reset-cold-start`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ 
                dry_run: false,
                reason: reason || "Bulk reset via admin UI",
                confirm: "RESET_MONITOR_COLD_START",
                extra_confirm: ["CLEAR_SEEN_ITEMS_NO_NOTIFY_BASELINE"],
                clear_found_items: clearFound,
                clear_seen_items: true
              }),
            });
            successCount++;
          } catch (e) {
            console.error(`Failed to reset monitor ${monitor.id}:`, e);
          }
        }
        toast.success(`Successfully reset ${successCount} monitors`);
        resetModals();
        return;
      }

      let endpoint = "";
      const body: MaintenanceBody = { 
        dry_run: false,
        reason: reason || "Admin maintenance UI",
        confirm: "",
        extra_confirm: []
      };

      if (activeAction === "retention") {
        endpoint = "/api/v1/maintenance/history-retention/cleanup";
        body.confirm = "CLEANUP_OLD_HISTORY";
        body.extra_confirm = ["CLEANUP_ALL_MONITORS_HISTORY"];
        body.include_found_items = clearFound;
        body.found_items_retention_days = retentionDays;
        if (confirmationInput !== body.confirm) throw new Error("Invalid confirmation string");
      } else if (activeAction === "pending_ack") {
        endpoint = "/api/v1/maintenance/pending-notifications/ack-no-notify";
        body.confirm = "ACK_PENDING_NO_NOTIFY";
        body.extra_confirm = ["ACK_ALL_SELECTED_PENDING_NO_NOTIFY"];
        if (confirmationInput !== body.confirm) throw new Error("Invalid confirmation string");
      }

      const res = await csrfFetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      await res.json();
      toast.success("Maintenance action completed");
      resetModals();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Live action failed";
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  };

  const getConfirmationString = () => {
    if (activeAction === "retention") return "CLEANUP_OLD_HISTORY";
    if (activeAction === "pending_ack") return "ACK_PENDING_NO_NOTIFY";
    if (activeAction === "reset_inactive") return "RESET_ALL_INACTIVE_MONITORS";
    return "";
  };

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Card className="glass-panel">
        <CardHeader>
          <div className="flex items-center gap-2">
            <History className="h-5 w-5 text-primary" />
            <CardTitle>History Retention</CardTitle>
          </div>
          <CardDescription>Cleanup old SeenItems and FoundItems history.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center space-x-2">
            <Checkbox 
              id="clear-found" 
              checked={clearFound} 
              onCheckedChange={(checked) => setClearFound(!!checked)} 
            />
            <Label htmlFor="clear-found">Include FoundItems (older than {retentionDays} days)</Label>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="retention-days">Retention days: {retentionDays}</Label>
            <Input 
              id="retention-days" 
              type="number" 
              value={retentionDays} 
              onChange={(e) => setRetentionDays(parseInt(e.target.value) || 30)} 
            />
          </div>
          <Button 
            variant="outline" 
            onClick={() => handleDryRun("retention")}
            disabled={isPending}
          >
            {isPending && activeAction === "retention" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCcw className="mr-2 h-4 w-4" />}
            Dry Run Cleanup
          </Button>
        </CardContent>
      </Card>

      <Card className="glass-panel">
        <CardHeader>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-primary" />
            <CardTitle>Pending Notifications</CardTitle>
          </div>
          <CardDescription>Acknowledge all pending notifications without sending them.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <p className="text-sm text-muted-foreground">This marks all notified=false items as notified=true across all monitors.</p>
          <Button 
            variant="outline" 
            onClick={() => handleDryRun("pending_ack")}
            disabled={isPending}
          >
            {isPending && activeAction === "pending_ack" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCcw className="mr-2 h-4 w-4" />}
            Dry Run Ack
          </Button>
        </CardContent>
      </Card>

      <Card className="glass-panel">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Radar className="h-5 w-5 text-primary" />
            <CardTitle>Bulk Reset</CardTitle>
          </div>
          <CardDescription>Reset all inactive monitors to cold-start state.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-center space-x-2">
            <Checkbox 
              id="bulk-clear-found" 
              checked={clearFound} 
              onCheckedChange={(checked) => setClearFound(!!checked)} 
            />
            <Label htmlFor="bulk-clear-found">Clear FoundItem history too</Label>
          </div>
          <Button 
            variant="outline" 
            onClick={() => handleDryRun("reset_inactive")}
            disabled={isPending}
          >
            {isPending && activeAction === "reset_inactive" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCcw className="mr-2 h-4 w-4" />}
            Dry Run Bulk Reset
          </Button>
        </CardContent>
      </Card>

      <Dialog open={!!dryRunResult} onOpenChange={(open) => !open && resetModals()}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-destructive" />
              Confirm Live Action
            </DialogTitle>
            <DialogDescription>
              Review the dry run results before proceeding with live mutation.
            </DialogDescription>
          </DialogHeader>
          
          {dryRunResult && (
            <div className="space-y-4 py-4">
              <div className="rounded-lg bg-muted p-3 text-sm space-y-1">
                {dryRunResult.inactive_monitors_count !== undefined && (
                  <p>Affected monitors: <strong>{dryRunResult.inactive_monitors_count}</strong></p>
                )}
                {dryRunResult.would_delete_seen_items !== undefined && (
                  <p>Would delete <strong>{dryRunResult.would_delete_seen_items}</strong> SeenItems.</p>
                )}
                {dryRunResult.would_delete_found_items !== undefined && (
                  <p>Would delete <strong>{dryRunResult.would_delete_found_items}</strong> FoundItems.</p>
                )}
                {dryRunResult.would_mark_notified_count !== undefined && (
                  <p>Would mark <strong>{dryRunResult.would_mark_notified_count}</strong> items as notified.</p>
                )}
                {dryRunResult.pending_found_items_count !== undefined && (
                  <p>Pending items count: <strong>{dryRunResult.pending_found_items_count}</strong></p>
                )}
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
                <Label htmlFor="reason">Reason for audit log</Label>
                <Input 
                  id="reason" 
                  placeholder="e.g. Manual cleanup for P1 maintenance" 
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="confirm">Type <strong>{getConfirmationString()}</strong> to confirm</Label>
                <Input 
                  id="confirm" 
                  placeholder="Confirmation string" 
                  value={confirmationInput}
                  onChange={(e) => setConfirmationInput(e.target.value)}
                />
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="ghost" onClick={resetModals} disabled={isPending}>Cancel</Button>
            <Button 
              variant="destructive" 
              onClick={handleLive}
              disabled={isPending || !reason || confirmationInput !== getConfirmationString()}
            >
              {isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
              Execute Live
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
