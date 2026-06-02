import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type DashboardCardProps = {
  title: string;
  value: string;
  icon: LucideIcon;
  compact?: boolean;
  className?: string;
};

export function DashboardCard({ title, value, icon: Icon, compact, className }: DashboardCardProps) {
  return (
    <Card className={cn("glass-panel overflow-hidden", className)}>
      <CardContent className={cn("relative p-5", compact && "p-4")}>
        <div className="absolute right-0 top-0 size-24 translate-x-8 -translate-y-8 rounded-full bg-emerald-300/10 blur-2xl" />
        <div className="relative flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-emerald-300/10 text-emerald-200 ring-1 ring-emerald-300/15">
            <Icon className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-muted-foreground">{title}</p>
            <p className={cn("mt-1 font-semibold tracking-tight", compact ? "text-sm leading-6" : "text-2xl")}>
              {value}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
