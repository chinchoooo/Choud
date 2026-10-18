import { Download, Lock, LockOpen, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";

import { formatBytes, formatDateTime } from "../lib/format";
import { ConfirmDialog, plainButton, primaryButton } from "../components/Dialogs";
import {
  CorruptVaultData,
  WrongPassphrase,
  createVault,
  decryptBytes,
  decryptJson,
  encryptBytes,
  encryptJson,
  unlockVault,
  type VaultConfig,
} from "../vault/crypto";
import {
  BLOB_SUFFIX,
  CONFIG_NAME,
  MANIFEST_NAME,
  MAX_VAULT_FILE_BYTES,
  createVaultFolder,
  findVaultFolder,
  listVault,
  readBytes,
  removeStored,
  writeBytes,
  type Manifest,
  type VaultListing,
} from "../vault/store";

const IDLE_LOCK_MS = 10 * 60_000;
const MIN_PASSPHRASE = 10;

type Phase = "loading" | "none" | "locked" | "open" | "error";

const field = "mt-1 block w-full max-w-sm border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md";

/**
 * An encrypted vault inside your drive. Files are sealed in this browser with a key made from your
 * passphrase; the server only stores ciphertext and never learns the passphrase or the file names.
 */
export function Vault() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [folderId, setFolderId] = useState<string | null>(null);
  const [listing, setListing] = useState<VaultListing | null>(null);
  const [manifest, setManifest] = useState<Manifest>({ version: 1, items: {} });
  const [passphrase, setPassphrase] = useState("");
  const [again, setAgain] = useState("");
  const [understood, setUnderstood] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  // The key lives only in memory and is dropped on lock, on idle and when leaving the page.
  const keyRef = useRef<CryptoKey | null>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const lock = useCallback((why?: string) => {
    keyRef.current = null;
    if (idleTimer.current) clearTimeout(idleTimer.current);
    setManifest({ version: 1, items: {} });
    setPassphrase("");
    setAgain("");
    setPhase((current) => (current === "open" ? "locked" : current));
    if (why) setMessage(why);
  }, []);

  const touch = useCallback(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => lock("Locked after 10 minutes without activity."), IDLE_LOCK_MS);
  }, [lock]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const id = await findVaultFolder();
        if (cancelled) return;
        if (id === null) return setPhase("none");
        setFolderId(id);
        const found = await listVault(id);
        if (cancelled) return;
        setListing(found);
        setPhase(found.config ? "locked" : "none");
      } catch (error) {
        if (!cancelled) {
          setMessage(error instanceof Error ? error.message : "Could not reach the server.");
          setPhase("error");
        }
      }
    })();
    return () => {
      cancelled = true;
      keyRef.current = null;
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, []);

  async function saveManifest(next: Manifest, key: CryptoKey, folder: string) {
    await writeBytes(folder, MANIFEST_NAME, await encryptJson(key, next));
    setManifest(next);
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (passphrase !== again) return setMessage("The two passphrases are different.");
    if (passphrase.length < MIN_PASSPHRASE) return setMessage(`Use at least ${MIN_PASSPHRASE} characters.`);
    setBusy(true);
    setMessage(null);
    try {
      const folder = folderId ?? (await createVaultFolder());
      setFolderId(folder);
      const { config, key } = await createVault(passphrase);
      await writeBytes(folder, CONFIG_NAME, new TextEncoder().encode(JSON.stringify(config)), "application/json");
      await saveManifest({ version: 1, items: {} }, key, folder);
      keyRef.current = key;
      setListing(await listVault(folder));
      setPassphrase("");
      setAgain("");
      setUnderstood(false);
      setPhase("open");
      touch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create the vault.");
    } finally {
      setBusy(false);
    }
  }

  async function unlock(event: FormEvent) {
    event.preventDefault();
    if (!folderId) return;
    setBusy(true);
    setMessage(null);
    try {
      const found = await listVault(folderId);
      if (!found.config) throw new CorruptVaultData("The vault settings file is missing.");
      const config = JSON.parse(new TextDecoder().decode(await readBytes(found.config.id))) as VaultConfig;
      const key = await unlockVault(config, passphrase);
      const loaded = found.manifest
        ? await decryptJson<Manifest>(key, await readBytes(found.manifest.id))
        : ({ version: 1, items: {} } as Manifest);
      keyRef.current = key;
      setListing(found);
      setManifest(loaded);
      setPassphrase("");
      setPhase("open");
      touch();
    } catch (error) {
      setMessage(
        error instanceof WrongPassphrase || error instanceof CorruptVaultData
          ? error.message
          : error instanceof Error
            ? error.message
            : "Could not open the vault.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = "";
    const key = keyRef.current;
    if (!key || !folderId || picked.length === 0) return;
    touch();
    setBusy(true);
    setMessage(null);
    let next: Manifest = { ...manifest, items: { ...manifest.items } };
    const skipped: string[] = [];
    try {
      for (const [index, file] of picked.entries()) {
        if (file.size > MAX_VAULT_FILE_BYTES) {
          skipped.push(file.name);
          continue;
        }
        setMessage(`Encrypting ${file.name} (${index + 1} of ${picked.length})…`);
        const id = crypto.randomUUID();
        const sealed = await encryptBytes(key, new Uint8Array(await file.arrayBuffer()));
        await writeBytes(folderId, `${id}${BLOB_SUFFIX}`, sealed);
        next = {
          ...next,
          items: {
            ...next.items,
            [id]: { name: file.name, size: file.size, type: file.type || "application/octet-stream", added: new Date().toISOString() },
          },
        };
        // The index is saved after every file, so an interrupted batch never orphans what was sent.
        await saveManifest(next, key, folderId);
      }
      setListing(await listVault(folderId));
      setMessage(
        skipped.length
          ? `Added. Skipped (over ${formatBytes(MAX_VAULT_FILE_BYTES)}): ${skipped.join(", ")}.`
          : `Added ${picked.length} file${picked.length === 1 ? "" : "s"} to the vault.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not add the files.");
    } finally {
      setBusy(false);
    }
  }

  async function download(id: string) {
    const key = keyRef.current;
    const stored = listing?.blobs.get(id);
    const item = manifest.items[id];
    if (!key || !stored || !item) return setMessage("That file is not in the vault any more.");
    touch();
    setBusy(true);
    setMessage(`Decrypting ${item.name}…`);
    try {
      const plain = await decryptBytes(key, await readBytes(stored.id));
      const url = URL.createObjectURL(new Blob([plain as BlobPart], { type: item.type }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = item.name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage(`Downloaded ${item.name}.`);
    } catch (error) {
      setMessage(error instanceof CorruptVaultData ? `${item.name}: ${error.message}` : "Could not read that file.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    const key = keyRef.current;
    const stored = listing?.blobs.get(id);
    if (!key || !folderId) return;
    setRemoving(null);
    setBusy(true);
    try {
      const items = { ...manifest.items };
      delete items[id];
      await saveManifest({ ...manifest, items }, key, folderId);
      if (stored) await removeStored(stored.id); // it waits in the server's trash like any file
      setListing(await listVault(folderId));
      setMessage("Removed from the vault.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not remove it.");
    } finally {
      setBusy(false);
    }
  }

  const entries = Object.entries(manifest.items).sort((a, b) => a[1].name.localeCompare(b[1].name));

  return (
    <div className="mx-auto max-w-3xl p-4 sm:p-6" onPointerDown={() => phase === "open" && touch()} onKeyDown={() => phase === "open" && touch()}>
      <h1 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
        <ShieldCheck size={18} aria-hidden /> Vault
      </h1>
      <p className="mt-1 text-sm text-gray-600">
        Files here are encrypted in your browser before they leave it. The server stores only scrambled data and can
        read neither the contents nor the file names, not even the administrator.
      </p>

      {phase === "loading" && <p className="mt-4 text-sm text-gray-500">Loading…</p>}
      {phase === "error" && (
        <p role="alert" className="mt-4 text-sm text-red-600">
          {message}
        </p>
      )}

      {phase === "none" && (
        <form onSubmit={(event) => void create(event)} className="mt-5">
          <h2 className="text-sm font-medium text-gray-900">Create your vault</h2>
          <label className="mt-3 block text-sm text-gray-700">
            Passphrase
            <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} autoComplete="new-password" className={field} />
          </label>
          <label className="mt-3 block text-sm text-gray-700">
            Passphrase again
            <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" className={field} />
          </label>
          <p className="mt-1 text-xs text-gray-500">At least {MIN_PASSPHRASE} characters. A few random words is best.</p>
          <label className="mt-3 flex max-w-md items-start gap-2 text-sm text-gray-800">
            <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} className="mt-1 accent-gray-900" />
            <span>I understand that if I forget this passphrase, nobody can recover what is in the vault, including me.</span>
          </label>
          <button type="submit" disabled={busy || !understood || passphrase.length === 0} className={`${primaryButton} mt-4`}>
            {busy ? "Creating…" : "Create vault"}
          </button>
        </form>
      )}

      {phase === "locked" && (
        <form onSubmit={(event) => void unlock(event)} className="mt-5">
          <h2 className="flex items-center gap-2 text-sm font-medium text-gray-900">
            <Lock size={14} aria-hidden /> The vault is locked
          </h2>
          <label className="mt-3 block text-sm text-gray-700">
            Passphrase
            <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} autoComplete="current-password" className={field} autoFocus />
          </label>
          <button type="submit" disabled={busy || passphrase.length === 0} className={`${primaryButton} mt-3`}>
            {busy ? "Unlocking…" : "Unlock"}
          </button>
        </form>
      )}

      {phase === "open" && (
        <>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <label className={`${primaryButton} inline-flex cursor-pointer items-center gap-1`}>
              <Plus size={14} aria-hidden /> Add files
              <input type="file" multiple className="hidden" onChange={(e) => void addFiles(e)} disabled={busy} aria-label="Add files to the vault" />
            </label>
            <button type="button" className={`${plainButton} inline-flex items-center gap-1`} onClick={() => lock("Locked.")}>
              <LockOpen size={14} aria-hidden /> Lock now
            </button>
            <span className="text-xs text-gray-500">Locks itself after 10 idle minutes.</span>
          </div>

          <ul className="mt-4 divide-y divide-gray-200 border border-gray-200 bg-white rounded-lg" aria-label="Vault files">
            {entries.length === 0 && <li className="p-4 text-sm text-gray-500">The vault is empty. Add files to seal them.</li>}
            {entries.map(([id, item]) => (
              <li key={id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate text-gray-900" title={item.name}>
                  {item.name}
                </span>
                <span className="text-xs text-gray-500">{formatBytes(item.size)}</span>
                <span className="hidden text-xs text-gray-400 sm:inline">{formatDateTime(item.added)}</span>
                <button type="button" className={`${plainButton} inline-flex items-center gap-1`} disabled={busy} onClick={() => void download(id)} aria-label={`Decrypt and download ${item.name}`}>
                  <Download size={14} aria-hidden /> Download
                </button>
                <button type="button" className={`${plainButton} inline-flex items-center gap-1`} disabled={busy} onClick={() => setRemoving(id)} aria-label={`Remove ${item.name}`}>
                  <Trash2 size={14} aria-hidden /> Remove
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {message && phase !== "error" && (
        <p role="status" className="mt-3 text-sm text-gray-800">
          {message}
        </p>
      )}

      <details className="mt-8 text-sm text-gray-600">
        <summary className="cursor-pointer font-medium text-gray-900">What the server can and cannot see</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>It cannot see your passphrase, your key, the contents, or the real file names (they are inside the sealed index).</li>
          <li>It can see that a folder called "Vault (encrypted)" exists, how many sealed files it holds, their sizes and when they were added.</li>
          <li>Vault files have no previews, thumbnails or search: nothing on the server can read them.</li>
          <li>Removed files wait in the trash, still sealed, until you delete them forever.</li>
          <li>The passphrase cannot be reset. Keep it somewhere safe, apart from this server.</li>
        </ul>
      </details>

      {removing && manifest.items[removing] && (
        <ConfirmDialog
          title="Remove from the vault?"
          message={`"${manifest.items[removing].name}" will be taken out of the vault. The sealed copy waits in the trash until you delete it forever.`}
          confirmLabel="Remove"
          danger
          onConfirm={() => void remove(removing)}
          onClose={() => setRemoving(null)}
        />
      )}
    </div>
  );
}
