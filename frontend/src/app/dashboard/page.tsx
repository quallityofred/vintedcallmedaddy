import { Activity, Bell, Clock, Radar } from "lucide-react";

import { AnimatedSection } from "@/components/animated-section";
import { DashboardCard } from "@/components/dashboard-card";
import { PageShell } from "@/components/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const cards = [
  { title: "Active monitors", value: "API pending", icon: Radar },
  { title: "Items today", value: "API pending", icon: Activity },
  { title: "Telegram status", value: "API pending", icon: Bell },
  { title: "Last discovery", value: "API pending", icon: Clock },
];

export default function DashboardPage() {
  return (
    <PageShell
      eyebrow="Dashboard shell"
      title="Monitor operations"
      description="A protected-layout preview for the future API-backed dashboard."
    >
      <AnimatedSection className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <DashboardCard key={card.title} {...card} />
        ))}
      </AnimatedSection>

      <AnimatedSection delay={0.08}>
        <Card className="glass-panel">
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Monitor table preview</CardTitle>
              <CardDescription>
                The first real dashboard pass will hydrate this table from `/api/v1/monitors`.
              </CardDescription>
            </div>
            <Badge variant="outline" className="w-fit">
              Read-only shell
            </Badge>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Domains</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Last check</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[0, 1, 2].map((row) => (
                  <TableRow key={row}>
                    <TableCell><Skeleton className="h-4 w-32" /></TableCell>
                    <TableCell><Skeleton className="h-4 w-24" /></TableCell>
                    <TableCell><Skeleton className="h-4 w-20" /></TableCell>
                    <TableCell className="flex justify-end"><Skeleton className="h-4 w-24" /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </AnimatedSection>
    </PageShell>
  );
}
