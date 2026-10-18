import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Server as ServerIcon } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import { getServerStatus } from "../api/insights";
import { checkPublicLinks, getInstance, revokeAllShares, setPublicLinks, type PublicCheck } from "../api/instance";
import { ConfirmDialog, plainButton } from "../components/Dialogs";
import { formatBytes } from "../lib/format";

function Row({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex justify-between gap-3 border-b border-gray-100 px-3 py-2 text-sm last:border-b-0">
      <dt className="text-gray-600">{label}</dt>
      <dd className={warn ? "font-semibold text-red-600" : "text-gray-900"}>{value}</dd>
    </div>
  );
}

const STATUS_TEXT = {
  ready: "On: share links work for anyone, from anywhere.",
  paused: "Paused: links only work on your private network until you resume.",
  not_configured: "Not set up: links only work on your private network.",
} as const;

/** Whether share links reach people outside the network, with the pause switch and the emergency button. */
function PublicLinksPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["instance"], queryFn: getInstance, retry: false });
  const [check, setCheck] = useState<PublicCheck | null>(null);
  const [revoked, setRevoked] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => setPublicLinks(enabled),
    onSuccess: (info) => queryClient.setQueryData(["instance"], info),
  });
  const run = useMutation({ mutationFn: checkPublicLinks, onSuccess: setCheck });
  const revoke = useMutation({
    mutationFn: revokeAllShares,
    onSuccess: (result) => {
      setConfirming(false);
      setRevoked(result.revoked);
    },
  });

  const info = query.data;
  if (!info) return null;
  return (
    <section className="mt-6 border border-gray-300 p-4 rounded-md" aria-label="Public share links">
      <h2 className="text-sm font-medium text-gray-900">Public share links</h2>
      <p role="status" className="mt-1 text-sm text-gray-700">
        {STATUS_TEXT[info.public_status]}
      </p>
      {info.public_base_url && <p className="mt-1 break-all font-mono text-xs text-gray-500">{info.public_base_url}</p>}
      {info.public_status === "not_configured" && (
        <p className="mt-2 text-xs text-gray-600">
          To turn it on, run <code className="font-mono">scripts/enable-public-links.sh</code> on the server. Only the share pages
          become reachable; the app and the API stay private.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {info.public_status !== "not_configured" && (
          <>
            <button type="button" className={plainButton} disabled={run.isPending} onClick={() => run.mutate()}>
              Check from outside
            </button>
            <button
              type="button"
              className={plainButton}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate(info.public_status === "paused")}
            >
              {info.public_status === "paused" ? "Resume public links" : "Pause public links"}
            </button>
          </>
        )}
        <button type="button" className={plainButton} onClick={() => setConfirming(true)}>
          Revoke all my links
        </button>
      </div>
      {check && (
        <p role="status" className="mt-3 text-sm text-gray-800">
          {check.ok ? "Works: " : "Problem: "}
          {check.detail}
        </p>
      )}
      {revoked !== null && (
        <p role="status" className="mt-3 text-sm text-gray-800">
          Revoked {revoked} link(s).
        </p>
      )}
      {confirming && (
        <ConfirmDialog
          title="Revoke all your links?"
          message="Every share link you have made stops working at once. People who had one will see a not-found page."
          confirmLabel="Revoke all"
          danger
          onConfirm={() => revoke.mutate()}
          onClose={() => setConfirming(false)}
        />
      )}
    </section>
  );
}

/** The administrator's view of the machine: disk, counts, the search backlog and settings. */
export function Server() {
  const query = useQuery({ queryKey: ["server-status"], queryFn: getServerStatus, retry: false, refetchInterval: 30_000 });

  if (query.error instanceof ApiError && query.error.status === 403) {
    return <p className="p-6 text-sm text-gray-600">Only the administrator can see the server.</p>;
  }
  if (query.isLoading) return <p className="p-6 text-sm text-gray-500">Loading…</p>;
  const s = query.data;
  if (!s) return <p className="p-6 text-sm text-red-600">Could not load the server status.</p>;

  const used = s.disk_total_bytes - s.disk_free_bytes;
  const pct = s.disk_total_bytes > 0 ? Math.round((used / s.disk_total_bytes) * 100) : 0;
  return (
    <div className="mx-auto max-w-2xl p-4 sm:p-6">
      <h1 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
        <ServerIcon size={18} aria-hidden /> Server
      </h1>
      <p className="mt-1 text-sm text-gray-600">How the machine running Choud is doing. Refreshes every 30 seconds.</p>

      <div
        role="progressbar"
        aria-label="Disk used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        className="mt-4 h-2 w-full overflow-hidden border border-gray-300 bg-gray-100"
      >
        <div className={`h-full ${pct >= 90 ? "bg-red-600" : "bg-gray-900"}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-gray-500">
        {formatBytes(s.disk_free_bytes)} free of {formatBytes(s.disk_total_bytes)} ({pct}% used)
      </p>

      <dl className="mt-4 border border-gray-200 bg-white rounded-md">
        <Row label="Accounts" value={String(s.users)} />
        <Row label="Files" value={String(s.files)} />
        <Row label="Versions" value={String(s.versions)} />
        <Row label="If nothing were shared (all versions)" value={formatBytes(s.logical_bytes)} />
        <Row label="Actually stored" value={formatBytes(s.stored_bytes)} />
        <Row label="Uploads in progress" value={String(s.uploads_in_progress)} />
        <Row label="Waiting to be indexed for search" value={String(s.index_pending)} />
        <Row label="Files the search could not read" value={String(s.index_failed)} warn={s.index_failed > 0} />
        <Row label="Who can register" value={s.registration_mode} />
        <Row label="Automatic clean-up of orphans" value={s.gc_delete_enabled ? "on" : "report only"} />
      </dl>

      <PublicLinksPanel />
    </div>
  );
}
