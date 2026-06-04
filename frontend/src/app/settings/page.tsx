"use client";

import { useEffect, useState, useCallback } from "react";
import { KeyRound, Loader2, Send, Globe, Cog } from "lucide-react";
import { toast } from "sonner";

import { AnimatedSection } from "@/components/animated-section";
import { AuthGuard } from "@/components/auth-guard";
import { PageShell } from "@/components/page-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface TelegramStatus {
  token_configured: boolean;
  chat_id_configured: boolean;
  bot_running: boolean;
  token_masked: string;
  chat_id_masked: string;
}

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
  
  const [cfUrl, setCfUrl] = useState("");
  const [cfBlock, setCfBlock] = useState("");
  const [cfRecovery, setCfRecovery] = useState("");

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
            setCfUrl(data.cloudflare_worker.url || "");
            setCfBlock(data.cloudflare_worker.block_threshold?.toString() || "");
            setCfRecovery(data.cloudflare_worker.recovery_minutes?.toString() || "");
        }
      }
    } catch {
      toast.error("Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);

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

  const handleUpdateTelegram = async () => {
    setSaving(true);
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
      if (!response.ok) throw new Error("Failed to update settings");
      toast.success("Settings updated");
      setToken("");
      setChatId("");
      void fetchSettings();
    } catch {
      toast.error("Failed to update settings");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateCfWorker = async () => {
    setSavingCf(true);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/settings/cloudflare-worker", {
        method: "PATCH",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          cf_worker_url: cfUrl,
          cf_worker_block_threshold: parseInt(cfBlock),
          cf_worker_recovery_minutes: parseInt(cfRecovery),
        }),
      });
      if (!response.ok) throw new Error("Failed to update settings");
      toast.success("Settings updated");
      void fetchSettings();
    } catch {
      toast.error("Failed to update settings");
    } finally {
      setSavingCf(false);
    }
  };

  const handleAction = async (action: "start" | "stop" | "test") => {
    setActionInFlight(action);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch(`/api/v1/telegram/${action}`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Failed to ${action} bot`);
      toast.success(`Action ${action} successful`);
      void fetchSettings();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Failed to ${action} bot`);
    } finally {
      setActionInFlight(null);
    }
  };

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
                <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                  <Button className="sm:w-auto" disabled={saving} onClick={handleUpdateTelegram}>
                    {saving ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />}
                    {saving ? "Saving" : "Save credentials"}
                  </Button>
                  <Button
                    disabled={actionInFlight !== null || !status?.token_configured || !status?.chat_id_configured}
                    onClick={() => handleAction("test")}
                    variant="outline"
                  >
                    {actionInFlight === "test" ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                    Send test
                  </Button>
                  {status?.bot_running ? (
                    <Button
                      disabled={actionInFlight !== null}
                      onClick={() => handleAction("stop")}
                      variant="destructive"
                    >
                      {actionInFlight === "stop" ? <Loader2 className="size-4 animate-spin" /> : null}
                      Stop bot
                    </Button>
                  ) : (
                    <Button
                      disabled={actionInFlight !== null || !status?.token_configured}
                      onClick={() => handleAction("start")}
                    >
                      {actionInFlight === "start" ? <Loader2 className="size-4 animate-spin" /> : null}
                      Start bot
                    </Button>
                  )}
                </div>
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
