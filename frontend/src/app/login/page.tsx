import Link from "next/link";
import { Lock, User } from "lucide-react";

import { AnimatedSection } from "@/components/animated-section";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <AnimatedSection className="w-full max-w-md">
        <Card className="glass-panel">
          <CardHeader className="space-y-3">
            <div className="flex size-12 items-center justify-center rounded-2xl bg-emerald-300/10 text-emerald-200">
              <Lock className="size-5" />
            </div>
            <div>
              <CardTitle className="text-2xl">Sign in preview</CardTitle>
              <CardDescription>
                Placeholder form for the upcoming JSON auth API. The legacy Jinja login still owns real sessions.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input id="username" placeholder="username" className="pl-9" disabled />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" placeholder="password" disabled />
            </div>
            <Button className="w-full" disabled>
              Login API pending
            </Button>
            <Separator />
            <p className="text-center text-sm text-muted-foreground">
              Need the current app?{" "}
              <Link href="http://localhost:8080/login" className="text-emerald-200 hover:underline">
                Open legacy login
              </Link>
            </p>
          </CardContent>
        </Card>
      </AnimatedSection>
    </main>
  );
}
