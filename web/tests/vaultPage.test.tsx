import { webcrypto } from "node:crypto";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { Vault } from "../src/pages/Vault";
import { ThemeProvider } from "../src/theme/ThemeContext";

// A tiny in-memory "server": file name -> bytes, so the test can inspect what would be stored.
const server = vi.hoisted(() => ({
  folder: null as string | null,
  files: new Map<string, { id: string; name: string; bytes: Uint8Array }>(),
  counter: 0,
}));

vi.mock("../src/vault/store", async () => {
  const actual = await vi.importActual<typeof import("../src/vault/store")>("../src/vault/store");
  const asFile = (entry: { id: string; name: string }) => ({ id: entry.id, name: entry.name }) as never;
  return {
    ...actual,
    findVaultFolder: async () => server.folder,
    createVaultFolder: async () => {
      server.folder = "folder-1";
      return "folder-1";
    },
    listVault: async () => {
      const blobs = new Map();
      let config = null;
      let manifest = null;
      for (const entry of server.files.values()) {
        if (entry.name === actual.CONFIG_NAME) config = asFile(entry);
        else if (entry.name === actual.MANIFEST_NAME) manifest = asFile(entry);
        else blobs.set(entry.name.replace(actual.BLOB_SUFFIX, ""), asFile(entry));
      }
      return { config, manifest, blobs };
    },
    readBytes: async (id: string) => [...server.files.values()].find((f) => f.id === id)!.bytes,
    writeBytes: async (_folder: string, name: string, bytes: Uint8Array) => {
      const existing = server.files.get(name);
      const id = existing?.id ?? `file-${++server.counter}`;
      server.files.set(name, { id, name, bytes: bytes.slice() });
      return { id, name } as never;
    },
    removeStored: async (id: string) => {
      for (const [name, entry] of server.files) if (entry.id === id) server.files.delete(name);
    },
  };
});

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
  if (!File.prototype.arrayBuffer) {
    File.prototype.arrayBuffer = function (this: File) {
      return new Promise<ArrayBuffer>((ok) => {
        const reader = new FileReader();
        reader.onload = () => ok(reader.result as ArrayBuffer);
        reader.readAsArrayBuffer(this);
      });
    };
  }
});

function renderVault() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter>
          <Vault />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

function allStored(): Buffer {
  return Buffer.concat([...server.files.values()].map((f) => Buffer.from(f.bytes)));
}

describe("Vault page", () => {
  it("creates a vault, seals files, locks, refuses a wrong passphrase and opens with the right one", async () => {
    const downloads: Blob[] = [];
    URL.createObjectURL = vi.fn((blob: Blob) => {
      downloads.push(blob);
      return "blob:fake";
    });
    URL.revokeObjectURL = vi.fn();
    HTMLAnchorElement.prototype.click = vi.fn();

    renderVault();
    expect(await screen.findByText("Create your vault")).toBeInTheDocument();

    const [pass, again] = screen.getAllByLabelText(/^passphrase/i);
    fireEvent.change(pass, { target: { value: "correct horse battery" } });
    fireEvent.change(again, { target: { value: "something else entirely" } });
    fireEvent.click(screen.getByLabelText(/i understand/i));
    fireEvent.click(screen.getByRole("button", { name: "Create vault" }));
    expect(await screen.findByText("The two passphrases are different.")).toBeInTheDocument();
    expect(server.files.size).toBe(0);

    fireEvent.change(again, { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: "Create vault" }));
    expect(await screen.findByLabelText("Vault files", {}, { timeout: 20000 })).toBeInTheDocument();
    expect([...server.files.keys()].sort()).toEqual(["manifest.cvault", "vault.json"]);
    expect(allStored().includes(Buffer.from("correct horse"))).toBe(false);

    // Add a file: only ciphertext reaches the server, and the real name appears only on screen.
    const secret = new File(["the launch code is 0451"], "launch-codes.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Add files to the vault"), { target: { files: [secret] } });
    expect(await screen.findByText("launch-codes.txt", {}, { timeout: 20000 })).toBeInTheDocument();
    const names = [...server.files.keys()];
    expect(names.some((n) => n.endsWith(".cvault") && n !== "manifest.cvault")).toBe(true);
    expect(names.join(" ")).not.toContain("launch-codes");
    expect(allStored().includes(Buffer.from("launch code"))).toBe(false);
    expect(allStored().includes(Buffer.from("launch-codes"))).toBe(false);

    // Locking forgets the key and hides the names.
    fireEvent.click(screen.getByRole("button", { name: /lock now/i }));
    expect(await screen.findByText("The vault is locked")).toBeInTheDocument();
    expect(screen.queryByText("launch-codes.txt")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Passphrase"), { target: { value: "not the passphrase" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/does not open this vault/i, {}, { timeout: 20000 })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Passphrase"), { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByText("launch-codes.txt", {}, { timeout: 20000 })).toBeInTheDocument();

    // Download decrypts back to the original bytes.
    fireEvent.click(screen.getByRole("button", { name: /decrypt and download launch-codes\.txt/i }));
    await waitFor(() => expect(downloads).toHaveLength(1));
    const text = await new Promise<string>((ok) => {
      const reader = new FileReader();
      reader.onload = () => ok(reader.result as string);
      reader.readAsText(downloads[0]);
    });
    expect(text).toBe("the launch code is 0451");

    // Removing updates the index and trashes the sealed file.
    fireEvent.click(screen.getByRole("button", { name: "Remove launch-codes.txt" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByText("launch-codes.txt")).not.toBeInTheDocument());
    expect([...server.files.keys()].filter((n) => n.endsWith(".cvault") && n !== "manifest.cvault")).toEqual([]);
  }, 90000);
});
