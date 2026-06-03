"use client";

import { useEffect, useState, useCallback } from "react";
import { Send, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { AnimatedSection } from "@/components/animated-section";
import { PageShell } from "@/components/page-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface TelegramStatus {
  configured: boolean;
  running: boolean;
}

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [token, setToken] = useState("");
  const [chatId, setChatId] = useState("");

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/telegram/status");
      if (response.ok) {
        setStatus(await response.json());
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
    const response = await fetch("/api/v1/auth/csrf");
    const { csrf_token } = await response.json();
    return csrf_token;
  };

  const handleUpdate = async () => {
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/settings/telegram", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ token: token || undefined, chat_id: chatId || undefined }),
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
              {status?.running 
                ? <Button variant="destructive" onClick={() => handleAction("stop")}>Stop Bot</Button>
                : <Button onClick={() => handleAction("start")} disabled={!status?.configured}>Start Bot</Button>
              }
            </div>
          </CardContent>
        </Card>
      </AnimatedSection>
    </PageShell>
  );
}
