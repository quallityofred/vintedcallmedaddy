import { Gauge, Send, Shield } from "lucide-react";

import { AnimatedSection } from "@/components/animated-section";
import { PageShell } from "@/components/page-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

export default function SettingsPage() {
  return (
    <PageShell
      eyebrow="Settings shell"
      title="Telegram and scraper controls"
      description="A non-submitting placeholder for the future safe settings API."
    >
      <AnimatedSection className="grid gap-5 lg:grid-cols-[1fr_0.8fr]">
        <Card className="glass-panel">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Send className="size-4 text-emerald-200" />
              Telegram
            </CardTitle>
            <CardDescription>
              Raw tokens will stay server-owned. This shell shows the future editing layout only.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="token">Bot token</Label>
              <Input id="token" type="password" placeholder="Stored securely by FastAPI" disabled />
            </div>
            <div className="space-y-2">
              <Label htmlFor="chat">Chat ID</Label>
              <Input id="chat" placeholder="Telegram chat ID" disabled />
            </div>
            <div className="flex gap-2">
              <Button disabled>Start bot</Button>
              <Button variant="outline" disabled>Send test</Button>
            </div>
          </CardContent>
        </Card>

        <Card className="glass-panel">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="size-4 text-emerald-200" />
              Scraper safety
            </CardTitle>
            <CardDescription>
              Existing rate limits and proxy behavior remain backend-owned.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="proxies">Proxy list</Label>
              <Textarea id="proxies" placeholder="One proxy per line" disabled />
            </div>
            <Separator />
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="sessions">Sessions</Label>
                <Input id="sessions" value="3" readOnly disabled />
              </div>
              <div className="space-y-2">
                <Label htmlFor="rate">Rate limit</Label>
                <Input id="rate" value="8/min" readOnly disabled />
              </div>
            </div>
          </CardContent>
        </Card>
      </AnimatedSection>

      <AnimatedSection delay={0.08}>
        <Alert className="glass-panel">
          <Gauge className="size-4" />
          <AlertTitle>API boundary pending</AlertTitle>
          <AlertDescription>
            Phase 1 intentionally does not change backend auth, CSRF, settings, scheduler, or Telegram behavior.
          </AlertDescription>
        </Alert>
      </AnimatedSection>

      <AnimatedSection delay={0.12} className="grid gap-4 md:grid-cols-3">
        {[
          "Token values should stay write-only in the new API.",
          "Proxy settings should continue to refresh scraper sessions server-side.",
          "Bot controls must keep CSRF headers and user ownership checks.",
        ].map((item) => (
          <div key={item} className="glass-panel rounded-2xl p-4 text-sm leading-6 text-muted-foreground">
            {item}
          </div>
        ))}
      </AnimatedSection>
    </PageShell>
  );
}
