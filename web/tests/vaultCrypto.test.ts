import { webcrypto } from "node:crypto";
import { beforeAll, describe, expect, it } from "vitest";

import {
  CHUNK_SIZE,
  CorruptVaultData,
  WrongPassphrase,
  createVault,
  decryptBytes,
  decryptJson,
  encryptBytes,
  encryptJson,
  fromBase64,
  toBase64,
  unlockVault,
} from "../src/vault/crypto";

// A few iterations keep the tests fast; the real default is 600,000.
const FAST = 100_000;

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
});

function bytes(length: number, seed = 7): Uint8Array {
  const out = new Uint8Array(length);
  for (let i = 0; i < length; i++) out[i] = (i * 31 + seed) & 0xff;
  return out;
}

describe("vault encryption", () => {
  it("round-trips small, empty and multi-chunk data", async () => {
    const { key } = await createVault("hunter2 hunter2", FAST);
    for (const size of [0, 1, 100, CHUNK_SIZE - 1, CHUNK_SIZE, CHUNK_SIZE + 1, 2 * CHUNK_SIZE + 5]) {
      const plain = bytes(size);
      const sealed = await encryptBytes(key, plain);
      expect(sealed.length).toBeGreaterThan(plain.length); // header + tags
      const back = await decryptBytes(key, sealed);
      expect(back.length).toBe(plain.length);
      expect(Buffer.from(back).equals(Buffer.from(plain))).toBe(true); // (toEqual on MiBs is very slow)
    }
  });

  it("never reveals the plain text, and seals the same data differently each time", async () => {
    const { key } = await createVault("a long passphrase", FAST);
    const plain = new TextEncoder().encode("my bank pin is 4921 and my secret name is Marmalade");
    const a = await encryptBytes(key, plain);
    const b = await encryptBytes(key, plain);
    expect(Buffer.from(a).includes(Buffer.from("Marmalade"))).toBe(false);
    expect(Buffer.from(a).equals(Buffer.from(b))).toBe(false);
  });

  it("detects a flipped bit, truncation, reordered chunks and a different key", async () => {
    const { key } = await createVault("passphrase one", FAST);
    const other = (await createVault("passphrase two", FAST)).key;
    const sealed = await encryptBytes(key, bytes(3 * CHUNK_SIZE));

    const flipped = sealed.slice();
    flipped[200] ^= 1;
    await expect(decryptBytes(key, flipped)).rejects.toBeInstanceOf(CorruptVaultData);

    const full = CHUNK_SIZE + 16;
    const truncated = sealed.slice(0, 13 + 2 * full); // the last chunk is gone
    await expect(decryptBytes(key, truncated)).rejects.toBeInstanceOf(CorruptVaultData);

    const swapped = sealed.slice();
    swapped.set(sealed.subarray(13 + full, 13 + 2 * full), 13);
    swapped.set(sealed.subarray(13, 13 + full), 13 + full);
    await expect(decryptBytes(key, swapped)).rejects.toBeInstanceOf(CorruptVaultData);

    await expect(decryptBytes(other, sealed)).rejects.toBeInstanceOf(CorruptVaultData);
    await expect(decryptBytes(key, new Uint8Array([1, 2, 3]))).rejects.toBeInstanceOf(CorruptVaultData);
  });

  it("round-trips JSON (the file index)", async () => {
    const { key } = await createVault("index passphrase", FAST);
    const index = { items: { a: { name: "passport.pdf", size: 12 } } };
    expect(await decryptJson(key, await encryptJson(key, index))).toEqual(index);
  });
});

describe("vault passphrase", () => {
  it("opens with the right passphrase and refuses a wrong one", async () => {
    const { config } = await createVault("correct horse battery", FAST);
    expect(config.iterations).toBe(FAST);
    expect(JSON.stringify(config)).not.toContain("correct horse"); // the config holds no secret

    const key = await unlockVault(config, "correct horse battery");
    expect(key.type).toBe("secret");
    await expect(unlockVault(config, "wrong passphrase")).rejects.toBeInstanceOf(WrongPassphrase);
    await expect(unlockVault(config, "")).rejects.toBeInstanceOf(WrongPassphrase);
  });

  it("refuses weak or unknown settings instead of trusting them", async () => {
    const { config } = await createVault("some passphrase", FAST);
    await expect(unlockVault({ ...config, iterations: 1000 }, "some passphrase")).rejects.toBeInstanceOf(
      CorruptVaultData,
    );
  });

  it("keeps keys apart: a key from another vault cannot open this data", async () => {
    const one = await createVault("same words", FAST);
    const two = await createVault("same words", FAST); // same passphrase, different random salt
    const sealed = await encryptBytes(one.key, bytes(50));
    await expect(decryptBytes(two.key, sealed)).rejects.toBeInstanceOf(CorruptVaultData);
  });
});

describe("base64 helpers", () => {
  it("round-trips arbitrary bytes", () => {
    const data = bytes(70_000, 3);
    expect(fromBase64(toBase64(data))).toEqual(data);
  });
});
