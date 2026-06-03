"use client";

import { useEffect, useState, useCallback } from "react";
import { KeyRound, Loader2, Send, ShieldCheck } from "lucide-react";
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
  const [actionInFlight, setActionInFlight] = useState<"start" | "stop" | "test" | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/telegram/status", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (response.ok) {
        const data = (await response.json()) as { telegram: TelegramStatus };
        setStatus(data.telegram);
      }
    } catch {
      toast.error("Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchStatus();
  }, [fetchStatus]);

  const getCsrfToken = async () => {
    const response = await fetch("/api/v1/auth/csrf", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const { csrf_token } = await response.json();
    return csrf_token;
  };

  const handleUpdate = async () => {
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
      void fetchStatus();
    } catch {
      toast.error("Failed to update settings");
    } finally {
      setSaving(false);
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
      if (!response.ok) throw new Error(`Failed to ${action} bot`);
      toast.success(`Action ${action} successful`);
      void fetchStatus();
    } catch {
      toast.error(`Failed to ${action} bot`);
    } finally {
      setActionInFlight(null);
    }
  };

  return (
    <PageShell
      eyebrow="Settings"
      title="Telegram Controls"
      description="Configure private notification delivery for this account."
    >
      <AnimatedSection className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
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
                  <Button className="sm:w-auto" disabled={saving} onClick={handleUpdate}>
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
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm">
                  <p className="font-medium">Saved credential status</p>
                  <p className="mt-2 text-muted-foreground">
                    Token: {status?.token_configured ? status.token_masked : "not configured"}
                    {" | "}
                    Chat: {status?.chat_id_configured ? status.chat_id_masked : "not configured"}
                  </p>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    Full token values are never rendered back into the browser after saving.
                  </p>
                </div>
              </>
            )}
          </CardContent>
        </Card>
        <Card className="glass-panel h-fit">
          <CardHeader className="border-b border-white/10 p-4 sm:p-6">
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-emerald-200" />
              Safety model
            </CardTitle>
            <CardDescription>Notification settings stay scoped to the current user.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 p-4 text-sm text-muted-foreground sm:p-6">
            <p>Credentials are stored server-side and are never exposed through frontend environment variables.</p>
            <p>Bot actions use CSRF-protected API calls through the same-origin `/api` rewrite.</p>
          </CardContent>
        </Card>
      </AnimatedSection>
    </PageShell>
  );
}
