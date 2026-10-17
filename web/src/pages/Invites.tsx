import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../api/client";
import { createInvite, deleteInvite, listInvites, type Invite } from "../api/invites";
import { plainButton, primaryButton } from "../components/Dialogs";
import { formatDateTime } from "../lib/format";

function status(invite: Invite): string {
  if (invite.used_at) return `used ${formatDateTime(invite.used_at)}`;
  if (invite.expires_at && new Date(invite.expires_at).getTime() < Date.now()) return "expired";
  return invite.expires_at ? `valid until ${formatDateTime(invite.expires_at)}` : "valid";
}

/** The administrator hands out one-time codes so people you trust can create an account. */
export function Invites() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["invites"], queryFn: listInvites, retry: false });
  const [note, setNote] = useState("");
  const [quota, setQuota] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["invites"] });

  const create = useMutation({
    mutationFn: () =>
      createInvite({ note: note.trim() || undefined, quotaGiB: quota ? Number(quota) : undefined }),
    onSuccess: () => {
      setNote("");
      setQuota("");
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: (id: string) => deleteInvite(id), onSuccess: refresh });

  if (query.error instanceof ApiError && query.error.status === 403) {
    return <p className="p-6 text-sm text-gray-600">Only the administrator can manage invites.</p>;
  }
  const invites = query.data ?? [];
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-gray-900">Invites</h1>
      <p className="mt-1 text-sm text-gray-600">
        Give someone a code and they can create their own account on this server. A code works once and
        expires after a week.
      </p>
      <form
        className="mt-4 flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <label className="text-sm text-gray-700">
          Who is it for
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={255}
            className="mt-1 block w-56 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900"
          />
        </label>
        <label className="text-sm text-gray-700">
          Storage limit in GB (optional)
          <input
            value={quota}
            onChange={(event) => setQuota(event.target.value.replace(/[^0-9.]/g, ""))}
            inputMode="decimal"
            className="mt-1 block w-40 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900"
          />
        </label>
        <button type="submit" disabled={create.isPending} className={primaryButton}>
          Create invite
        </button>
      </form>
      {create.error && <p role="alert" className="mt-2 text-sm text-red-600">Could not create the invite.</p>}
      <ul className="mt-4 divide-y divide-gray-200 border border-gray-200 rounded-md">
        {invites.length === 0 && <li className="p-3 text-sm text-gray-500">No invites yet.</li>}
        {invites.map((invite) => (
          <li key={invite.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
            <code className="font-mono text-gray-900">{invite.code}</code>
            <span className="text-gray-600">{invite.note ?? "no note"}</span>
            <span className="text-gray-500">{status(invite)}</span>
            <button className={`${plainButton} ml-auto`} onClick={() => remove.mutate(invite.id)}>
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
