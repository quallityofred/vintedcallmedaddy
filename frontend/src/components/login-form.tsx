"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AlertCircle, LoaderCircle, Lock, User } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

type LoginFormProps = {
  legacyLoginUrl?: string;
};

async function getCsrfToken() {
  const response = await fetch("/api/v1/auth/csrf", {
    cache: "no-store",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error("Unable to prepare secure login");
  }

  const payload = (await response.json()) as { csrf_token?: string };
  if (!payload.csrf_token) {
    throw new Error("Missing CSRF token");
  }
  return payload.csrf_token;
}

export function LoginForm({ legacyLoginUrl }: LoginFormProps) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(false);
    setIsSubmitting(true);

    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        setError(response.status === 401 ? "Invalid username or password." : "Login failed. Try again.");
        return;
      }

      setSuccess(true);
      router.push("/dashboard");
      router.refresh();
    } catch {
      setError("Unable to reach the authentication API.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="glass-panel">
      <CardHeader className="space-y-3">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-emerald-300/10 text-emerald-200">
          <Lock className="size-5" />
        </div>
        <div>
          <h1 className="font-heading text-2xl font-medium leading-snug">Sign in</h1>
          <CardDescription>
            Use your Vinted Monitor account. Sessions are issued by the FastAPI backend through the `/api` proxy.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <div className="relative">
              <User className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                autoComplete="username"
                className="pl-9"
                disabled={isSubmitting}
                id="username"
                onChange={(event) => setUsername(event.target.value)}
                placeholder="username"
                required
                value={username}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              autoComplete="current-password"
              disabled={isSubmitting}
              id="password"
              onChange={(event) => setPassword(event.target.value)}
              placeholder="password"
              required
              type="password"
              value={password}
            />
          </div>

          {error ? (
            <Alert className="border-red-300/20 bg-red-400/10 text-red-100" variant="destructive">
              <AlertCircle className="size-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {success ? (
            <Alert className="border-emerald-300/20 bg-emerald-400/10 text-emerald-100">
              <AlertDescription>Signed in. Opening dashboard...</AlertDescription>
            </Alert>
          ) : null}

          <Button className="h-10 w-full" disabled={isSubmitting} type="submit">
            {isSubmitting ? (
              <>
                <LoaderCircle className="size-4 animate-spin" />
                Signing in
              </>
            ) : (
              "Sign in"
            )}
          </Button>
        </form>

        {legacyLoginUrl ? (
          <>
            <Separator />
            <p className="text-center text-sm text-muted-foreground">
              Need the current backend page?{" "}
              <Link href={legacyLoginUrl} className="text-emerald-200 hover:underline">
                Open legacy login
              </Link>
            </p>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
