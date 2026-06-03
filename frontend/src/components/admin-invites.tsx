"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Loader2, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface InviteCode {
  id: number;
  code: string;
  is_active: boolean;
  max_uses: number;
  used_count: number;
}

export function AdminInvites() {
  const [invites, setInvites] = useState<InviteCode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [creating, setCreating] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const fetchInvites = useCallback(async () => {
    setError(false);
    try {
      const response = await fetch("/api/v1/admin/invites", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) throw new Error("Failed to load invites");
      const data = (await response.json()) as InviteCode[];
      setInvites(data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchInvites();
  }, [fetchInvites]);

  const getCsrfToken = async () => {
    const response = await fetch("/api/v1/auth/csrf", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    const { csrf_token } = (await response.json()) as { csrf_token: string };
    return csrf_token;
  };

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreating(true);

    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/admin/invites", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ code: newCode.trim() || undefined, max_uses: 1 }),
      });
      if (!response.ok) throw new Error("Failed to create invite");
      toast.success("Invite created");
      setNewCode("");
      void fetchInvites();
    } catch {
      toast.error("Invite could not be created");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    setDeletingId(id);
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch(`/api/v1/admin/invites/${id}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
      });
      if (!response.ok) throw new Error("Failed to delete invite");
      toast.success("Invite revoked");
      void fetchInvites();
    } catch {
      toast.error("Invite could not be revoked");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <Card className="glass-panel overflow-hidden">
      <CardHeader className="border-b border-white/10 p-4 sm:p-6">
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-emerald-200" />
          Invite Management
        </CardTitle>
        <CardDescription>Create single-use invite codes and revoke unused codes.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-3 sm:p-5">
        <form className="grid gap-3 rounded-2xl border border-white/10 bg-white/[0.03] p-3 sm:grid-cols-[1fr_auto]" onSubmit={handleCreate}>
          <div className="grid gap-2">
            <Label htmlFor="invite-code">Invite code</Label>
            <Input
              disabled={creating}
              id="invite-code"
              onChange={(event) => setNewCode(event.target.value)}
              placeholder="Leave blank to generate one"
              value={newCode}
            />
          </div>
          <div className="flex items-end">
            <Button className="w-full sm:w-auto" disabled={creating} type="submit">
              {creating ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
              {creating ? "Creating" : "Create invite"}
            </Button>
          </div>
        </form>

        {loading ? (
          <div className="flex h-32 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-muted-foreground">
            <Loader2 className="size-5 animate-spin text-emerald-200" />
            <p className="mt-2 text-sm">Loading invites</p>
          </div>
        ) : error ? (
          <div className="flex h-32 items-center justify-center rounded-2xl border border-red-300/20 bg-red-400/10 px-4 text-center text-sm text-red-100">
            Invite codes could not be loaded.
          </div>
        ) : invites.length === 0 ? (
          <div className="flex h-32 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] px-4 text-center">
            <p className="text-sm font-medium">No invite codes</p>
            <p className="mt-1 text-sm text-muted-foreground">Create an invite when a new user needs access.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl border border-white/10 bg-black/10">
            <div className="overflow-x-auto">
              <Table className="min-w-[560px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Code</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Uses</TableHead>
                    <TableHead className="text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invites.map((invite) => (
                    <TableRow key={invite.id}>
                      <TableCell className="font-mono text-sm">{invite.code}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {invite.is_active ? "Active" : "Disabled"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {invite.used_count} / {invite.max_uses}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          aria-label={`Revoke invite ${invite.code}`}
                          className="text-destructive hover:bg-destructive/10"
                          disabled={deletingId === invite.id}
                          onClick={() => handleDelete(invite.id)}
                          size="icon-sm"
                          title="Revoke invite"
                          variant="ghost"
                        >
                          {deletingId === invite.id ? (
                            <Loader2 className="size-4 animate-spin" />
                          ) : (
                            <Trash2 className="size-4" />
                          )}
                        </Button>
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
