/**
 * The Vault's cryptography: everything happens in the browser with the Web Crypto API, so the
 * server only ever stores ciphertext and never sees the passphrase, the key, or the file names.
 *
 *  - Key: PBKDF2-SHA256 (600,000 iterations, random 16-byte salt) from the passphrase -> AES-256-GCM.
 *  - Data: split into 1 MiB chunks, each sealed with AES-GCM under its own IV (an 8-byte random
 *    per-file nonce + a 4-byte counter). The chunk number and a "last chunk" flag are authenticated,
 *    so reordering, dropping or truncating chunks is detected, not just flipped bits.
 *  - A wrong passphrase is recognised by decrypting a small sealed check value.
 *
 * Losing the passphrase means losing the data: there is no recovery.
 */

export const PBKDF2_ITERATIONS = 600_000;
export const CHUNK_SIZE = 1024 * 1024;
const MAGIC = new Uint8Array([0x43, 0x56, 0x4c, 0x54, 0x31]); // "CVLT1"
const HEADER = MAGIC.length + 8; // magic + 8-byte file nonce
const TAG = 16;
const CHECK_TEXT = "choud-vault-check-v1";

export interface VaultConfig {
  version: 1;
  salt: string; // base64
  iterations: number;
  check: string; // base64 of an encrypted CHECK_TEXT
}

export class WrongPassphrase extends Error {
  constructor() {
    super("That passphrase does not open this vault.");
  }
}

export class CorruptVaultData extends Error {
  constructor(message = "This data is damaged or was changed.") {
    super(message);
  }
}

function subtle(): SubtleCrypto {
  const s = globalThis.crypto?.subtle;
  if (!s) throw new Error("This browser cannot do encryption here (it needs a secure page, https or localhost).");
  return s;
}

export function toBase64(bytes: Uint8Array): string {
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

export function fromBase64(text: string): Uint8Array {
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function deriveKey(passphrase: string, salt: BufferSource, iterations: number): Promise<CryptoKey> {
  const material = await subtle().importKey("raw", new TextEncoder().encode(passphrase), "PBKDF2", false, ["deriveKey"]);
  return subtle().deriveKey(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

/** Our byte arrays are always plain ArrayBuffers (never shared memory), which is what Web Crypto wants. */
const asBuffer = (bytes: Uint8Array): Uint8Array<ArrayBuffer> => bytes as Uint8Array<ArrayBuffer>;

function chunkIv(nonce: Uint8Array, counter: number): Uint8Array<ArrayBuffer> {
  const iv = new Uint8Array(12);
  iv.set(nonce, 0);
  new DataView(iv.buffer).setUint32(8, counter, false);
  return iv;
}

function chunkAad(counter: number, last: boolean): Uint8Array<ArrayBuffer> {
  const aad = new Uint8Array(5);
  new DataView(aad.buffer).setUint32(0, counter, false);
  aad[4] = last ? 1 : 0;
  return aad;
}

/** Seals `data` (any size) into the chunked format. */
export async function encryptBytes(key: CryptoKey, data: Uint8Array): Promise<Uint8Array> {
  const nonce = crypto.getRandomValues(new Uint8Array(8));
  const chunks = Math.max(1, Math.ceil(data.length / CHUNK_SIZE));
  const parts: Uint8Array[] = [MAGIC, nonce];
  for (let i = 0; i < chunks; i++) {
    const slice = data.subarray(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    const sealed = await subtle().encrypt(
      { name: "AES-GCM", iv: chunkIv(nonce, i), additionalData: chunkAad(i, i === chunks - 1), tagLength: 128 },
      key,
      asBuffer(slice),
    );
    parts.push(new Uint8Array(sealed));
  }
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

/** Opens data made by `encryptBytes`. Throws CorruptVaultData if anything was changed or cut off. */
export async function decryptBytes(key: CryptoKey, sealed: Uint8Array): Promise<Uint8Array> {
  if (sealed.length < HEADER + TAG || !MAGIC.every((byte, i) => sealed[i] === byte)) {
    throw new CorruptVaultData("This is not Vault data.");
  }
  const nonce = sealed.subarray(MAGIC.length, HEADER);
  const body = sealed.subarray(HEADER);
  const full = CHUNK_SIZE + TAG;
  const chunks = Math.ceil(body.length / full);
  const pieces: Uint8Array[] = [];
  try {
    for (let i = 0; i < chunks; i++) {
      const piece = body.subarray(i * full, (i + 1) * full);
      const plain = await subtle().decrypt(
        { name: "AES-GCM", iv: chunkIv(nonce, i), additionalData: chunkAad(i, i === chunks - 1), tagLength: 128 },
        key,
        asBuffer(piece),
      );
      pieces.push(new Uint8Array(plain));
    }
  } catch {
    throw new CorruptVaultData();
  }
  const out = new Uint8Array(pieces.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const piece of pieces) {
    out.set(piece, offset);
    offset += piece.length;
  }
  return out;
}

export async function encryptJson(key: CryptoKey, value: unknown): Promise<Uint8Array> {
  return encryptBytes(key, new TextEncoder().encode(JSON.stringify(value)));
}

export async function decryptJson<T>(key: CryptoKey, sealed: Uint8Array): Promise<T> {
  return JSON.parse(new TextDecoder().decode(await decryptBytes(key, sealed))) as T;
}

/** A new vault: the public config to store next to the data, and the key to use right now. */
export async function createVault(
  passphrase: string,
  iterations = PBKDF2_ITERATIONS,
): Promise<{ config: VaultConfig; key: CryptoKey }> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const key = await deriveKey(passphrase, salt, iterations);
  const check = await encryptBytes(key, new TextEncoder().encode(CHECK_TEXT));
  return { config: { version: 1, salt: toBase64(salt), iterations, check: toBase64(check) }, key };
}

/** Derives the key from a passphrase and proves it is right; throws WrongPassphrase otherwise. */
export async function unlockVault(config: VaultConfig, passphrase: string): Promise<CryptoKey> {
  if (config.version !== 1 || config.iterations < 100_000) throw new CorruptVaultData("Unsupported vault settings.");
  const key = await deriveKey(passphrase, asBuffer(fromBase64(config.salt)), config.iterations);
  try {
    const text = new TextDecoder().decode(await decryptBytes(key, fromBase64(config.check)));
    if (text !== CHECK_TEXT) throw new WrongPassphrase();
  } catch (error) {
    if (error instanceof WrongPassphrase) throw error;
    throw new WrongPassphrase();
  }
  return key;
}
