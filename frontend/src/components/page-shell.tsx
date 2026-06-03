import Link from "next/link";
import { LayoutDashboard, LogIn, Radar, Settings } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Landing", icon: Radar },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/login", label: "Login", icon: LogIn },
];

type PageShellProps = {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
};

export function PageShell({ eyebrow, title, description, children }: PageShellProps) {
  return (
    <main className="min-h-screen">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 py-4 sm:py-6 lg:px-6">
        <div className="grid flex-1 gap-4 sm:gap-5 lg:grid-cols-[17rem_1fr]">
          <aside className="glass-panel rounded-3xl p-4 lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)]">
            <Link href="/" className="flex items-center gap-3 rounded-2xl px-2 py-3">
              <div className="flex size-10 items-center justify-center rounded-2xl bg-emerald-300/10 text-emerald-200">
                <Radar className="size-5" />
              </div>
              <div>
                <p className="font-semibold tracking-tight">Vinted Monitor</p>
                <p className="text-xs text-muted-foreground">Operations console</p>
              </div>
            </Link>
            <Separator className="my-4" />
            <nav className="grid gap-1">
              {navItems.map((item) => {
                const Icon = item.icon;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      buttonVariants({ variant: "ghost" }),
                      "h-10 justify-start gap-3 px-3 text-muted-foreground hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </aside>
          <section className="space-y-5 py-2 sm:space-y-6 lg:py-6">
            <header className="glass-panel rounded-3xl p-5 sm:p-7">
              <p className="text-sm font-medium uppercase tracking-[0.28em] text-emerald-200/80">{eyebrow}</p>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{title}</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
            </header>
            {children}
          </section>
        </div>
      </div>
    </main>
  );
}
