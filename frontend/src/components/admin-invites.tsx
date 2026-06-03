"use client";

import { useEffect, useState, useCallback } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
  const [newCode, setNewCode] = useState("");

  const fetchInvites = useCallback(async () => {
    try {
      const response = await fetch("/api/v1/admin/invites", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (response.ok) {
        const data = await response.json();
        setInvites(data);
      }
    } catch {
      toast.error("Failed to load invites");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchInvites();
  }, [fetchInvites]);

  const getCsrfToken = async () => {
    const response = await fetch("/api/v1/auth/csrf");
    const { csrf_token } = await response.json();
    return csrf_token;
  };

  const handleCreate = async () => {
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch("/api/v1/admin/invites", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ code: newCode, max_uses: 1 }),
      });
      if (!response.ok) throw new Error("Failed to create invite");
      toast.success("Invite created");
      setNewCode("");
      void fetchInvites();
    } catch {
      toast.error("Failed to create invite");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const csrfToken = await getCsrfToken();
      const response = await fetch(`/api/v1/admin/invites/${id}`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": csrfToken },
      });
      if (!response.ok) throw new Error("Failed to delete invite");
      toast.success("Invite revoked");
      void fetchInvites();
    } catch {
      toast.error("Failed to delete invite");
    }
  };

  if (loading) return <Loader2 className="animate-spin" />;

  return (
    <Card className="glass-panel">
      <CardHeader>
        <CardTitle>Invite Management</CardTitle>
        <CardDescription>Manage invite codes for new users.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex gap-2 mb-4">
          <Input 
            value={newCode} 
            onChange={(e) => setNewCode(e.target.value)} 
            placeholder="Custom code (optional)"
          />
          <Button onClick={handleCreate}><Plus className="size-4 mr-2" />Create</Button>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Code</TableHead>
              <TableHead>Uses</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {invites.map((invite) => (
              <TableRow key={invite.id}>
                <TableCell className="font-mono">{invite.code}</TableCell>
                <TableCell>{invite.used_count} / {invite.max_uses}</TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="icon" onClick={() => handleDelete(invite.id)}>
                    <Trash2 className="size-4 text-destructive" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
