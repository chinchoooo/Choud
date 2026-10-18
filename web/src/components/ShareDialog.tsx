import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "../api/client";
import { DOWNLOAD_LIMITS, EXPIRY_CHOICES, createShare, shareUrl, type Share } from "../api/shares";
import { Modal, plainButton, primaryButton } from "./Dialogs";

/** Copies text; falls back to selecting it when the clipboard API is unavailable (plain http). */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

interface Props {
  /** What is being shared: one file or one folder. */
  target: { kind: "file" | "folder"; id: string; name: string };
  onClose: () => void;
}

/** Make a public link: choose how long it lasts and whether it has a password, then copy it. */
export function ShareDialog({ target, onClose }: Props) {
  const queryClient = useQueryClient();
  const [expiry, setExpiry] = useState<number | null>(null);
  const [password, setPassword] = useState("");
  const [permission, setPermission] = useState<"view" | "edit" | "drop">("view");
  const [maxDownloads, setMaxDownloads] = useState<number | null>(null);
  const [created, setCreated] = useState<Share | null>(null);
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createShare({
        ...(target.kind === "file" ? { fileId: target.id } : { folderId: target.id }),
        expiresInHours: expiry,
        password: password || undefined,
        permission,
        ...(maxDownloads && permission !== "drop" ? { maxDownloads } : {}),
      }),
    onSuccess: (share) => {
      setCreated(share);
      void queryClient.invalidateQueries({ queryKey: ["shares"] });
    },
  });

  const error =
    mutation.error instanceof ApiError
      ? mutation.error.message
      : mutation.error
        ? "Could not create the link."
        : null;
  const passwordTooShort = password.length > 0 && password.length < 4;

  if (created) {
    const url = shareUrl(created);
    return (
      <Modal title={`Link for "${target.name}"`} onClose={onClose}>
        <p className="text-sm text-gray-700">
          Anyone with this link can{" "}
          {created.permission === "drop"
            ? "send files into the folder, without seeing what is in it"
            : created.permission === "edit"
            ? target.kind === "folder"
              ? "open the folder, add files and change them"
              : "see the file and upload new versions"
            : target.kind === "folder"
              ? "open the folder"
              : "see and download the file"}
          {created.expires_at ? " until it expires" : ""}
          {created.has_password ? ", after entering the password" : ""}.
        </p>
        {created.public_status && created.public_status !== "ready" && (
          <p role="note" className="mt-2 border border-gray-300 bg-gray-50 px-3 py-2 text-xs text-gray-800 rounded-md">
            {created.public_status === "paused"
              ? "Public links are paused, so this link only works on your private network."
              : "This link only works for people on your network. Ask the administrator to run scripts/enable-public-links.sh to make links work from anywhere."}
          </p>
        )}
        <input
          readOnly
          value={url}
          aria-label="Share link"
          onFocus={(event) => event.currentTarget.select()}
          className="mt-3 w-full border border-gray-300 bg-white px-3 py-2 font-mono text-xs text-gray-900 rounded-md"
        />
        <p role="status" className="mt-2 min-h-5 text-xs text-gray-500">
          {copied === "yes" && "Copied."}
          {copied === "no" && "Could not copy automatically: select the link and copy it."}
        </p>
        <div className="mt-3 flex justify-end gap-2">
          <button onClick={onClose} className={plainButton}>
            Done
          </button>
          <button
            onClick={async () => setCopied((await copyText(url)) ? "yes" : "no")}
            className={primaryButton}
          >
            Copy link
          </button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={`Share "${target.name}"`} onClose={onClose}>
      <p className="text-sm text-gray-700">
        Make a link anyone can open, without an account. You can turn it off any time from Shared links.
      </p>
      <label className="mt-3 block text-sm text-gray-700">
        People with the link can
        <select
          value={permission}
          onChange={(event) => setPermission(event.target.value as "view" | "edit" | "drop")}
          className="mt-1 w-full border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md"
        >
          <option value="view">View and download</option>
          <option value="edit">Add, rename and delete files</option>
          {target.kind === "folder" && <option value="drop">Only send me files (a file request)</option>}
        </select>
      </label>
      {permission === "drop" && (
        <p className="mt-1 text-xs text-gray-500">
          Visitors see only an upload form. They cannot see, download or change anything in the folder, and a file with
          the same name is saved as "name (2)".
        </p>
      )}
      {permission === "edit" && (
        <p className="mt-1 text-xs text-gray-500">
          Anyone who gets this link can change the {target.kind}. Deleted files go to your trash and
          replaced files keep their old version. Set an expiry or a password.
        </p>
      )}
      <label className="mt-3 block text-sm text-gray-700">
        Link works for
        <select
          value={expiry ?? ""}
          onChange={(event) => setExpiry(event.target.value === "" ? null : Number(event.target.value))}
          className="mt-1 w-full border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md"
        >
          {EXPIRY_CHOICES.map((choice) => (
            <option key={choice.label} value={choice.hours ?? ""}>
              {choice.label}
            </option>
          ))}
        </select>
      </label>
      {permission !== "drop" && (
        <label className="mt-3 block text-sm text-gray-700">
          Stops working after
          <select
            value={maxDownloads ?? ""}
            onChange={(event) => setMaxDownloads(event.target.value === "" ? null : Number(event.target.value))}
            className="mt-1 w-full border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md"
          >
            {DOWNLOAD_LIMITS.map((choice) => (
              <option key={choice.label} value={choice.count ?? ""}>
                {choice.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="mt-3 block text-sm text-gray-700">
        Password (optional)
        <input
          type="password"
          value={password}
          autoComplete="new-password"
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1 w-full border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md"
        />
      </label>
      {passwordTooShort && <p className="mt-1 text-xs text-red-600">Use at least 4 characters.</p>}
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className={plainButton}>
          Cancel
        </button>
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || passwordTooShort}
          className={primaryButton}
        >
          {mutation.isPending ? "Creating…" : "Create link"}
        </button>
      </div>
    </Modal>
  );
}
