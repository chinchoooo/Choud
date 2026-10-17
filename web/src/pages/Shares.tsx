import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { revokeShare, listShares, shareUrl, type Share } from "../api/shares";
import { ConfirmDialog, plainButton } from "../components/Dialogs";
import { formatDateTime } from "../lib/format";

function expiryText(share: Share): string {
  if (!share.expires_at) return "never expires";
  const when = new Date(share.expires_at);
  return when.getTime() < Date.now() ? "expired" : `expires ${formatDateTime(share.expires_at)}`;
}

/** Every public link you have made, so you can copy one again or switch it off. */
export function Shares() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["shares"], queryFn: listShares, refetchInterval: 30_000 });
  const [revoking, setRevoking] = useState<Share | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const revoke = useMutation({
    mutationFn: (share: Share) => revokeShare(share.id),
    onSuccess: () => {
      setRevoking(null);
      void queryClient.invalidateQueries({ queryKey: ["shares"] });
    },
  });

  async function copy(share: Share) {
    try {
      await navigator.clipboard.writeText(shareUrl(share));
      setCopiedId(share.id);
      setTimeout(() => setCopiedId((current) => (current === share.id ? null : current)), 2000);
    } catch {
      window.prompt("Copy this link:", shareUrl(share));
    }
  }

  const shares = query.data ?? [];
  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Shared links</h1>
          <p className="text-xs text-gray-500">Public links you made. Revoking one stops it at once.</p>
        </div>
        <button onClick={() => void query.refetch()} className={plainButton}>
          {query.isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="mt-4 border border-gray-200 bg-white rounded-lg">
        {query.isLoading && <p className="p-4 text-sm text-gray-500">Loading…</p>}
        {query.isError && <p className="p-4 text-sm text-red-600">Could not load your links.</p>}
        {query.isSuccess && shares.length === 0 && (
          <p className="p-4 text-sm text-gray-500">
            No links yet. Open the ⋯ menu on a file or folder and choose “Share link…”.
          </p>
        )}
        <ul>
          {shares.map((share) => (
            <li key={share.id} className="border-b border-gray-100 px-4 py-3 last:border-b-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-gray-900" title={share.target_name}>
                    {share.kind === "folder" ? "[+] " : ""}
                    {share.target_name}
                  </div>
                  <div className="text-xs text-gray-500">
                    {expiryText(share)}
                    {share.has_password ? " · password" : ""}
                    {` · ${share.download_count} download${share.download_count === 1 ? "" : "s"}`}
                    {share.last_accessed_at ? ` · last opened ${formatDateTime(share.last_accessed_at)}` : ""}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => void copy(share)} className={plainButton}>
                    {copiedId === share.id ? "Copied" : "Copy link"}
                  </button>
                  <button onClick={() => setRevoking(share)} className={plainButton}>
                    Revoke
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {revoking && (
        <ConfirmDialog
          title="Revoke this link?"
          message={`Anyone using the link to "${revoking.target_name}" will lose access immediately.`}
          confirmLabel="Revoke"
          danger
          onClose={() => setRevoking(null)}
          onConfirm={() => revoke.mutate(revoking)}
        />
      )}
    </div>
  );
}
