"use client";

import { useEffect, useState, useCallback } from "react";
import { Send, Loader2 } from "lucide-react";
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
    }
  };

  const handleAction = async (action: "start" | "stop" | "test") => {
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
    }
  };

  if (loading) return <Loader2 className="animate-spin" />;

  return (
    <PageShell
      eyebrow="Settings"
      title="Telegram Controls"
      description="Configure your Telegram bot for notifications."
    >
      <AnimatedSection className="grid gap-5 lg:grid-cols-[1fr_0.8fr]">
        <Card className="glass-panel">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Send className="size-4 text-emerald-200" />
              Telegram Bot
            </CardTitle>
            <CardDescription>
              Configure credentials. Tokens are write-only.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="token">Bot token (leave empty to keep current)</Label>
              <Input id="token" type="password" value={token} onChange={(e) => setToken(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="chat">Chat ID</Label>
              <Input id="chat" value={chatId} onChange={(e) => setChatId(e.target.value)} />
            </div>
            <div className="flex gap-2">
              <Button onClick={handleUpdate}>Save Credentials</Button>
              <Button variant="outline" onClick={() => handleAction("test")}>Send Test</Button>
              {status?.bot_running
                ? <Button variant="destructive" onClick={() => handleAction("stop")}>Stop Bot</Button>
                : <Button onClick={() => handleAction("start")} disabled={!status?.token_configured}>Start Bot</Button>
              }
            </div>
            <p className="text-xs text-muted-foreground">
              Saved token: {status?.token_configured ? status.token_masked : "not configured"}.
              {" "}Saved chat: {status?.chat_id_configured ? status.chat_id_masked : "not configured"}.
            </p>
          </CardContent>
        </Card>
      </AnimatedSection>
    </PageShell>
  );
}
