"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, EyeOff, Loader2, PackageSearch } from "lucide-react";
import { toast } from "sonner";

import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

interface FoundItem {
  id: number;
  title: string;
  price: number;
  currency: string;
  brand: string;
  size: string;
  condition: string;
  item_url: string;
  seller_id: number;
  found_at: string;
}

export function FoundItemsList() {
  const [items, setItems] = useState<FoundItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [hidingSellerId, setHidingSellerId] = useState<number | null>(null);

  const fetchItems = useCallback(async () => {
    setError(false);
    try {
      const response = await fetch("/api/v1/items?limit=10", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Failed to fetch items");
      const data = (await response.json()) as { items: FoundItem[] };
      setItems(data.items);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchItems();
  }, [fetchItems]);

  const getCsrfToken = async () => {
    const response = await fetch("/api/v1/auth/csrf", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const { csrf_token } = (await response.json()) as { csrf_token: string };
    return csrf_token;
  };

  const handleHideSeller = async (sellerId: number) => {
    setHidingSellerId(sellerId);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/hidden-sellers", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ seller_id: sellerId }),
      });
      if (!response.ok) throw new Error("Failed to hide seller");
      toast.success("Seller hidden");
      void fetchItems();
    } catch {
      toast.error("Seller could not be hidden");
    } finally {
      setHidingSellerId(null);
    }
  };

  return (
    <Card className="glass-panel overflow-hidden">
      <CardHeader className="border-b border-white/10 p-4 sm:p-6">
        <CardTitle className="flex items-center gap-2">
          <PackageSearch className="size-4 text-emerald-200" />
          Recent items
        </CardTitle>
        <CardDescription>Latest user-scoped findings across active monitors.</CardDescription>
      </CardHeader>
      <CardContent className="p-3 sm:p-5">
        {loading ? (
          <div className="flex h-36 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-muted-foreground">
            <Loader2 className="size-5 animate-spin text-emerald-200" />
            <p className="mt-2 text-sm">Loading recent items</p>
          </div>
        ) : error ? (
          <div className="flex h-36 items-center justify-center rounded-2xl border border-red-300/20 bg-red-400/10 px-4 text-center text-sm text-red-100">
            Recent items could not be loaded. Refresh the page or try again later.
          </div>
        ) : items.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] px-4 text-center">
            <PackageSearch className="mb-3 size-8 text-emerald-200/80" />
            <p className="text-sm font-medium">No findings yet</p>
            <p className="mt-1 max-w-sm text-sm text-muted-foreground">
              New matches will appear here after active monitors discover items.
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-white/10 bg-black/10">
            <div className="overflow-x-auto">
              <Table className="min-w-[720px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Item</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="max-w-[28rem]">
                        <div className="truncate font-medium">{item.title}</div>
                        <div className="mt-1 truncate text-xs text-muted-foreground">
                          {[item.brand, item.size, item.condition].filter(Boolean).join(" - ")}
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-medium tabular-nums">
                        {item.price} {item.currency}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <a
                            aria-label={`Open listing ${item.title}`}
                            className={cn(buttonVariants({ variant: "ghost", size: "icon-xs" }))}
                            href={item.item_url}
                            rel="noreferrer"
                            target="_blank"
                            title="Open listing"
                          >
                            <ExternalLink className="size-3.5" />
                          </a>
                          <Button
                            aria-label={`Hide seller ${item.seller_id}`}
                            className="text-amber-300 hover:text-amber-200"
                            disabled={hidingSellerId === item.seller_id}
                            onClick={() => handleHideSeller(item.seller_id)}
                            size="icon-xs"
                            title="Hide seller"
                            variant="ghost"
                          >
                            {hidingSellerId === item.seller_id ? (
                              <Loader2 className="size-3.5 animate-spin" />
                            ) : (
                              <EyeOff className="size-3.5" />
                            )}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
