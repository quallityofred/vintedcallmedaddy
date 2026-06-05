import { useState } from "react";
import { Loader2, RefreshCcw, Send } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ensureMonitorTopic, testMonitorTopic, MonitorTopicStatus } from "@/lib/telegram-topics";

interface Props {
  monitorId: number;
  topicsEnabled: boolean;
  status: MonitorTopicStatus | null;
  onStatusChange: (monitorId: number, status: MonitorTopicStatus | null) => void;
}

export function MonitorTelegramTopicPanel({ monitorId, topicsEnabled, status, onStatusChange }: Props) {
  const [actionLoading, setActionLoading] = useState<"ensure" | "test" | null>(null);

  if (!topicsEnabled) return null;

  const getCsrfToken = async () => {
    const response = await fetch("/api/v1/auth/csrf", { cache: "no-store" });
    const { csrf_token } = (await response.json()) as { csrf_token: string };
    return csrf_token;
  };

  const handleAction = async (action: "ensure" | "test") => {
    setActionLoading(action);
    try {
      const csrfToken = await getCsrfToken();
      if (action === "ensure") {
        const data = await ensureMonitorTopic(monitorId, csrfToken);
        onStatusChange(monitorId, data);
        toast.success("Topic ensured");
      } else {
        const { message, topic } = await testMonitorTopic(monitorId, csrfToken);
        if (topic) {
          onStatusChange(monitorId, { ...topic, monitor_id: monitorId });
        }
        toast.success(message);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed");
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="mt-2 rounded-xl border border-white/10 bg-black/20 p-3 text-xs">
        {status ? (
            <div className="space-y-2">
                <p>Status: <span className="font-medium">{status.status}</span></p>
                {status.topic_name && <p>Topic: {status.topic_name}</p>}
                {status.last_error && <p className="text-red-400">Error: {status.last_error}</p>}
                
                <div className="flex gap-2">
                    <Button size="sm" variant="outline" disabled={actionLoading !== null} onClick={() => handleAction("ensure")}>
                        {actionLoading === "ensure" ? <Loader2 className="size-3 animate-spin"/> : <RefreshCcw className="size-3"/>}
                        Ensure
                    </Button>
                    <Button size="sm" variant="outline" disabled={actionLoading !== null} onClick={() => handleAction("test")}>
                        {actionLoading === "test" ? <Loader2 className="size-3 animate-spin"/> : <Send className="size-3"/>}
                        Test
                    </Button>
                </div>
            </div>
        ) : (
            <div className="space-y-2">
                <p>Status: <span className="font-medium">not_created</span></p>
                <div className="flex gap-2">
                    <Button size="sm" variant="outline" disabled={actionLoading !== null} onClick={() => handleAction("ensure")}>
                        {actionLoading === "ensure" ? <Loader2 className="size-3 animate-spin"/> : <RefreshCcw className="size-3"/>}
                        Ensure
                    </Button>
                </div>
            </div>
        )}
    </div>
  );
}
