"use client";

import { useEffect, useState, useCallback } from "react";
import { ExternalLink, Loader2, EyeOff } from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button, buttonVariants } from "@/components/ui/button";
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

  const fetchItems = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/items?limit=10", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Failed to fetch items");
      const data = await response.json();
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
    const response = await fetch("/api/v1/auth/csrf");
    const { csrf_token } = await response.json();
    return csrf_token;
  };

  const handleHideSeller = async (sellerId: number) => {
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/hidden-sellers", {
        method: "POST",
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
      toast.error("Failed to hide seller");
    }
  };

  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle>Recent Found Items</CardTitle>
        <CardDescription>Latest items found across your monitors.</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex h-32 items-center justify-center text-muted-foreground">
            <Loader2 className="size-6 animate-spin opacity-20" />
          </div>
        ) : error ? (
          <div className="h-32 text-center text-red-400">Failed to load items.</div>
        ) : items.length === 0 ? (
          <div className="h-32 text-center text-muted-foreground">No items found yet.</div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-white/10">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead>Price</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell>
                      <div className="font-medium">{item.title}</div>
                      <div className="text-xs text-muted-foreground">{item.brand} • {item.size} • {item.condition}</div>
                    </TableCell>
                    <TableCell>{item.price} {item.currency}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <a 
                          href={item.item_url} 
                          target="_blank" 
                          rel="noreferrer"
                          className={cn(buttonVariants({ variant: "ghost", size: "icon-xs" }))}
                          title="View"
                        >
                          <ExternalLink className="size-3.5" />
                        </a>
                        <Button 
                          variant="ghost" 
                          size="icon-xs" 
                          title="Hide Seller"
                          onClick={() => handleHideSeller(item.seller_id)}
                          className="text-amber-400 hover:text-amber-300"
                        >
                          <EyeOff className="size-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
