"use client";

import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, CheckCircle2, Cog, Globe, KeyRound, Loader2, Send } from "lucide-react";
import { toast } from "sonner";

import { AnimatedSection } from "@/components/animated-section";
import { AuthGuard } from "@/components/auth-guard";
import { PageShell } from "@/components/page-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { 
    Select, 
    SelectContent, 
    SelectItem, 
    SelectTrigger, 
} from "@/components/ui/select";

interface TelegramStatus {
  token_configured: boolean;
  chat_id_configured: boolean;
  bot_running: boolean;
  token_masked: string;
  chat_id_masked: string;
}

interface ApiErrorPayload {
  detail?: string;
  message?: string;
  code?: string;
}

type CfWorkerMode = "auto" | "direct" | "worker";

interface CloudflareWorkerPayload {
  url?: string | null;
  block_threshold?: number | null;
  recovery_minutes?: number | null;
  mode?: string | null;
}

type Notice = {
  type: "success" | "error" | "info";
  text: string;
};

const normalizeCfMode = (value: unknown): CfWorkerMode => {
  return value === "direct" || value === "worker" || value === "auto" ? value : "auto";
};

const cfModeLabels: Record<CfWorkerMode, string> = {
  auto: "Auto",
  direct: "Direct only",
  worker: "CF Worker only",
};

export default function SettingsPage() {
  return (
    <AuthGuard>
      <SettingsContent />
    </AuthGuard>
  );
}

function SettingsContent() {
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [saving, setSaving] = useState(false);
  const [savingCf, setSavingCf] = useState(false);
  const [actionInFlight, setActionInFlight] = useState<"start" | "stop" | "test" | null>(null);
  const [telegramNotice, setTelegramNotice] = useState<Notice | null>(null);
  
  const [cfUrl, setCfUrl] = useState("");
  const [cfBlock, setCfBlock] = useState("");
  const [cfRecovery, setCfRecovery] = useState("");
  const [cfMode, setCfMode] = useState<CfWorkerMode>("auto");
  const [cfNotice, setCfNotice] = useState<Notice | null>(null);

  const applyCloudflareWorkerState = useCallback((payload: CloudflareWorkerPayload) => {
    setCfUrl(payload.url || "");
    setCfBlock(payload.block_threshold?.toString() || "");
    setCfRecovery(payload.recovery_minutes?.toString() || "");
    setCfMode(normalizeCfMode(payload.mode));
  }, []);

  const fetchSettings = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/settings", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (response.ok) {
        const data = await response.json();
        setStatus(data.telegram);
        if (data.cloudflare_worker) {
            applyCloudflareWorkerState(data.cloudflare_worker);
        }
      }
    } catch {
      toast.error("Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, [applyCloudflareWorkerState]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchSettings();
  }, [fetchSettings]);

  const getCsrfToken = async () => {
    const response = await fetch("/api/v1/auth/csrf", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const { csrf_token } = await response.json();
    return csrf_token;
  };

  const readApiMessage = async (response: Response, fallback: string) => {
    try {
      const data = (await response.json()) as ApiErrorPayload;
      return data.detail || data.message || fallback;
    } catch {
      return fallback;
    }
  };

  const parseOptionalInteger = (value: string, label: string) => {
    const trimmed = value.trim();
    if (!trimmed) return undefined;
    const parsed = Number(trimmed);
    if (!Number.isInteger(parsed)) {
      throw new Error(`${label} must be a whole number.`);
    }
    return parsed;
  };

  const handleUpdateTelegram = async () => {
    setSaving(true);
    setTelegramNotice(null);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/settings/telegram", {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          telegram_bot_token: token || undefined,
          telegram_chat_id: chatId || undefined,
        }),
      });
      if (!response.ok) throw new Error(await readApiMessage(response, "Telegram credentials could not be saved"));
      const message = "Telegram credentials saved. Saved values remain masked.";
      toast.success(message);
      setTelegramNotice({ type: "success", text: message });
      setToken("");
      setChatId("");
      void fetchSettings();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Telegram credentials could not be saved";
      toast.error(message);
      setTelegramNotice({ type: "error", text: message });
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateCfWorker = async () => {
    setSavingCf(true);
    setCfNotice(null);
    try {
      const csrfToken = await getCsrfToken();
      
      const payload: { 
        cf_worker_url?: string;
        cf_worker_mode: CfWorkerMode;
        cf_worker_block_threshold?: number; 
        cf_worker_recovery_minutes?: number 
      } = {
        cf_worker_mode: cfMode,
      };

      payload.cf_worker_url = cfUrl.trim();
      
      const blockThreshold = parseOptionalInteger(cfBlock, "Block threshold");
      if (blockThreshold !== undefined) payload.cf_worker_block_threshold = blockThreshold;

      const recoveryMinutes = parseOptionalInteger(cfRecovery, "Recovery minutes");
      if (recoveryMinutes !== undefined) payload.cf_worker_recovery_minutes = recoveryMinutes;
      
      const response = await fetch("/api/v1/settings/cloudflare-worker", {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiMessage(response, "Failed to update settings"));
      const data = await response.json();
      if (data.cloudflare_worker) {
        applyCloudflareWorkerState(data.cloudflare_worker);
      }
      toast.success("Settings updated");
      setCfNotice({ type: "success", text: "Cloudflare Worker settings saved." });
      await fetchSettings();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to update settings";
      toast.error(message);
      setCfNotice({ type: "error", text: message });
    } finally {
      setSavingCf(false);
    }
  };

  const handleAction = async (action: "start" | "stop" | "test") => {
    setActionInFlight(action);
    setTelegramNotice(null);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch(`/api/v1/telegram/${action}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
      });
      const data = (await response.json()) as ApiErrorPayload;
      if (!response.ok) throw new Error(data.detail || data.message || `Failed to ${action} bot`);
      const successMessage =
        action === "test"
          ? "Telegram test message sent."
          : data.message || `Telegram bot ${action === "start" ? "started" : "stopped"}.`;
      toast.success(successMessage);
      setTelegramNotice({ type: "success", text: successMessage });
      void fetchSettings();
    } catch (err) {
      const message = err instanceof Error ? err.message : `Failed to ${action} bot`;
      toast.error(message);
      setTelegramNotice({ type: "error", text: message });
    } finally {
      setActionInFlight(null);
    }
  };

  const tokenConfigured = Boolean(status?.token_configured);
  const chatConfigured = Boolean(status?.chat_id_configured);
  const telegramConfigured = tokenConfigured && chatConfigured;
  const testDisabledReason = !tokenConfigured
    ? "Add and save a bot token before sending a test message."
    : !chatConfigured
      ? "Add and save a chat ID before sending a test message."
      : null;
  const startDisabledReason = !tokenConfigured ? "Add and save a bot token before starting the bot." : null;

  return (
    <PageShell
      eyebrow="Settings"
      title="Configuration"
      description="Manage your notification and personal scraper settings."
    >
      <AnimatedSection className="grid gap-5">
        <Card className="glass-panel">
          <CardHeader className="border-b border-white/10 p-4 sm:p-6">
            <CardTitle className="flex items-center gap-2">
              <Send className="size-4 text-emerald-200" />
              Telegram Bot
            </CardTitle>
            <CardDescription>Tokens are write-only. Saved credentials are shown only as masked status.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5 p-4 sm:p-6">
            {loading ? (
              <div className="flex h-40 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-muted-foreground">
                <Loader2 className="size-5 animate-spin text-emerald-200" />
                <p className="mt-2 text-sm">Loading Telegram settings</p>
              </div>
            ) : (
              <>
                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-2xl border border-white/10 bg-black/15 p-3">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Bot token</p>
                    <p className="mt-2 text-sm font-medium">
                      {tokenConfigured ? status?.token_masked || "Configured" : "Not configured"}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-black/15 p-3">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Chat ID</p>
                    <p className="mt-2 text-sm font-medium">
                      {chatConfigured ? status?.chat_id_masked || "Configured" : "Not configured"}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-black/15 p-3">
                    <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Bot runtime</p>
                    <p className="mt-2 inline-flex items-center gap-2 text-sm font-medium">
                      {status?.bot_running ? (
                        <>
                          <CheckCircle2 className="size-4 text-emerald-200" />
                          Running
                        </>
                      ) : (
                        "Stopped"
                      )}
                    </p>
                  </div>
                </div>

                {telegramNotice ? (
                  <div
                    className={
                      telegramNotice.type === "error"
                        ? "rounded-2xl border border-red-300/20 bg-red-400/10 p-3 text-sm text-red-100"
                        : "rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-3 text-sm text-emerald-50"
                    }
                  >
                    <div className="flex gap-2">
                      {telegramNotice.type === "error" ? (
                        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                      ) : (
                        <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                      )}
                      <p>{telegramNotice.text}</p>
                    </div>
                  </div>
                ) : null}

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="token">Bot token</Label>
                    <Input
                      autoComplete="off"
                      disabled={saving}
                      id="token"
                      onChange={(event) => setToken(event.target.value)}
                      placeholder="Leave empty to keep saved token"
                      type="password"
                      value={token}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="chat">Chat ID</Label>
                    <Input
                      autoComplete="off"
                      disabled={saving}
                      id="chat"
                      onChange={(event) => setChatId(event.target.value)}
                      placeholder="Leave empty to keep saved chat"
                      value={chatId}
                    />
                  </div>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
                  <p className="text-sm font-medium">Credential safety</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    Tokens and chat IDs are write-only in this form. After saving, only masked values are returned by
                    the API and shown here.
                  </p>
                </div>

                <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                  <Button className="sm:w-auto" disabled={saving} onClick={handleUpdateTelegram}>
                    {saving ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />}
                    {saving ? "Saving" : "Save credentials"}
                  </Button>
                  <Button
                    disabled={actionInFlight !== null || !telegramConfigured}
                    onClick={() => handleAction("test")}
                    variant="outline"
                  >
                    {actionInFlight === "test" ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                    {actionInFlight === "test" ? "Sending test" : "Send test"}
                  </Button>
                  {status?.bot_running ? (
                    <Button
                      disabled={actionInFlight !== null}
                      onClick={() => handleAction("stop")}
                      variant="destructive"
                    >
                      {actionInFlight === "stop" ? <Loader2 className="size-4 animate-spin" /> : null}
                      {actionInFlight === "stop" ? "Stopping" : "Stop bot"}
                    </Button>
                  ) : (
                    <Button
                      disabled={actionInFlight !== null || !tokenConfigured}
                      onClick={() => handleAction("start")}
                    >
                      {actionInFlight === "start" ? <Loader2 className="size-4 animate-spin" /> : null}
                      {actionInFlight === "start" ? "Starting" : "Start bot"}
                    </Button>
                  )}
                </div>
                {testDisabledReason || startDisabledReason ? (
                  <p className="text-xs leading-5 text-muted-foreground">
                    {testDisabledReason || startDisabledReason}
                  </p>
                ) : null}
              </>
            )}
          </CardContent>
        </Card>

        <Card className="glass-panel">
          <CardHeader className="border-b border-white/10 p-4 sm:p-6">
            <CardTitle className="flex items-center gap-2">
              <Globe className="size-4 text-emerald-200" />
              Your Cloudflare Worker
            </CardTitle>
            <CardDescription>Used only for your own monitors.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5 p-4 sm:p-6">
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2 md:col-span-3">
                <Label htmlFor="cfUrl">Worker URL</Label>
                <Input
                  disabled={savingCf}
                  id="cfUrl"
                  onChange={(event) => setCfUrl(event.target.value)}
                  placeholder="https://worker.example.com"
                  value={cfUrl}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cfMode">Routing Mode</Label>
                <Select value={cfMode} onValueChange={(val) => setCfMode(normalizeCfMode(val))}>
                  <SelectTrigger id="cfMode">
                    <span className="flex flex-1 text-left">{cfModeLabels[cfMode]}</span>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Auto (Direct first, fallback to Worker)</SelectItem>
                    <SelectItem value="direct">Direct only</SelectItem>
                    <SelectItem value="worker">CF Worker only</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                    {cfMode === "auto" && "Uses direct first, falls back to Worker if blocked."}
                    {cfMode === "direct" && "Never uses Worker."}
                    {cfMode === "worker" && "Always uses Worker."}
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="cfBlock">Block threshold</Label>
                <Input
                  disabled={savingCf}
                  id="cfBlock"
                  type="number"
                  onChange={(event) => setCfBlock(event.target.value)}
                  value={cfBlock}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cfRecovery">Recovery minutes</Label>
                <Input
                  disabled={savingCf}
                  id="cfRecovery"
                  type="number"
                  onChange={(event) => setCfRecovery(event.target.value)}
                  value={cfRecovery}
                />
              </div>
            </div>
            {cfNotice ? (
              <div
                className={
                  cfNotice.type === "error"
                    ? "rounded-2xl border border-red-300/20 bg-red-400/10 p-3 text-sm text-red-100"
                    : "rounded-2xl border border-emerald-300/20 bg-emerald-300/10 p-3 text-sm text-emerald-50"
                }
              >
                <div className="flex gap-2">
                  {cfNotice.type === "error" ? (
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  ) : (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                  )}
                  <p>{cfNotice.text}</p>
                </div>
              </div>
            ) : null}
            <Button className="sm:w-auto" disabled={savingCf} onClick={handleUpdateCfWorker}>
              {savingCf ? <Loader2 className="size-4 animate-spin" /> : <Cog className="size-4" />}
              {savingCf ? "Saving" : "Save settings"}
            </Button>
            <p className="text-xs text-muted-foreground">If no Worker is configured, checks run without CF Worker.</p>
          </CardContent>
        </Card>
      </AnimatedSection>
    </PageShell>
  );
}
