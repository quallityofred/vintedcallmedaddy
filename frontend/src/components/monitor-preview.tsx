import { Bell, Clock3, ExternalLink, Radar, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const demoMonitors = [
  {
    name: "Nike Dunk Low",
    domain: "vinted.fr",
    interval: "120s",
    status: "Active",
    found: "14",
  },
  {
    name: "Carhartt Detroit",
    domain: "vinted.de",
    interval: "180s",
    status: "Cooling",
    found: "6",
  },
  {
    name: "Arc'teryx Shell",
    domain: "vinted.it",
    interval: "240s",
    status: "Active",
    found: "9",
  },
];

const events = [
  { label: "DB-level dedup checked", icon: ShieldCheck },
  { label: "Telegram notification queued", icon: Bell },
  { label: "Adaptive interval preserved", icon: Clock3 },
];

export function MonitorPreview() {
  return (
    <Card className="glass-panel overflow-hidden">
      <CardHeader className="border-b border-white/10">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Radar className="size-4 text-emerald-200" />
              Monitor command preview
            </CardTitle>
            <CardDescription>
              Demo placeholder. Real values will come from `/api/v1/monitors`.
            </CardDescription>
          </div>
          <Badge variant="outline" className="w-fit border-emerald-300/20 text-emerald-200">
            Demo data
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-5 p-4 lg:grid-cols-[1fr_17rem]">
        <div className="overflow-hidden rounded-2xl border border-white/10">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Search</TableHead>
                <TableHead>Domain</TableHead>
                <TableHead>Interval</TableHead>
                <TableHead className="text-right">Found</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {demoMonitors.map((monitor) => (
                <TableRow key={monitor.name}>
                  <TableCell>
                    <div className="font-medium">{monitor.name}</div>
                    <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                      <ExternalLink className="size-3" />
                      API pending
                    </div>
                  </TableCell>
                  <TableCell>{monitor.domain}</TableCell>
                  <TableCell>{monitor.interval}</TableCell>
                  <TableCell className="text-right">
                    <span className="font-semibold text-emerald-200">{monitor.found}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="space-y-3">
          {events.map((event) => (
            <div key={event.label} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <div className="mb-3 flex size-9 items-center justify-center rounded-xl bg-emerald-300/10 text-emerald-200">
                <event.icon className="size-4" />
              </div>
              <p className="text-sm font-medium">{event.label}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                Placeholder state until the API-backed flow is implemented.
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
