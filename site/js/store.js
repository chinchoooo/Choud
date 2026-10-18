// "Drop a file on the cloud": hashes the file in this tab with Web Crypto and prints the storage
// receipt Choud would write. The naming rule is the engine's own (objects/<first two hex>/<hash>).
// Nothing is uploaded: this page has no server to send it to.

const LIMIT = 100 * 1024 * 1024; // above this, reading the whole file could crash a phone tab
const root = document.querySelector("[data-store]");

if (root) {
  const drop = root.querySelector(".drop");
  const input = root.querySelector("#file");
  const receipt = root.querySelector("#receipt");
  const logoBtn = root.querySelector("#use-logo");
  const live = root.querySelector("#live");
  const canHash = !!(window.crypto && window.crypto.subtle);

  const LOGO_HASH = receipt.dataset.hash;
  // hash -> names it has been stored under (the logo is already "stored" when the page loads)
  const stored = new Map([[LOGO_HASH, ["choud-logo-light.png"]]]);

  const bytes = (n) => n.toLocaleString("en-US");
  const size = (n) => (n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB");

  function fingerprint(canvas, hex) {
    const ctx = canvas.getContext("2d");
    const ink = getComputedStyle(document.documentElement).getPropertyValue("--ink").trim() || "#000";
    const paper = getComputedStyle(document.documentElement).getPropertyValue("--paper").trim() || "#fff";
    ctx.fillStyle = paper;
    ctx.fillRect(0, 0, 16, 16);
    ctx.fillStyle = ink;
    for (let i = 0; i < 256; i++) {
      const byte = parseInt(hex.substr((i >> 3) * 2, 2), 16);
      if ((byte >> (7 - (i & 7))) & 1) ctx.fillRect(i & 15, i >> 4, 1, 1);
    }
  }

  function row(dl, label, value) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.append(dt, dd);
  }

  function render({ name, length, hex, ms, duplicate, names }) {
    receipt.textContent = "";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = "RECEIPT " + "─".repeat(18);
    const dl = document.createElement("dl");
    row(dl, "file", name + " · " + size(length));
    row(dl, "sha256", hex.slice(0, 16) + "…" + hex.slice(-8));
    row(dl, "stored at", "objects/" + hex.slice(0, 2) + "/" + hex.slice(0, 12) + "…");
    row(dl, "written", duplicate ? "0 bytes (already there)" : bytes(length) + " bytes · flushed, then renamed");
    row(dl, "hashed in", ms + " ms, on your device");
    const fpRow = document.createElement("div");
    fpRow.className = "fp-row";
    const canvas = document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "The file's 256-bit hash drawn as a 16 by 16 pixel image");
    fingerprint(canvas, hex);
    const cap = document.createElement("span");
    cap.className = "small";
    cap.textContent = "Its fingerprint: all 256 bits of the hash, one pixel each.";
    fpRow.append(canvas, cap);
    const verdict = document.createElement("p");
    verdict.className = "verdict" + (duplicate ? " dup" : "");
    verdict.textContent = duplicate
      ? "Already stored. " + names.length + " names, 1 copy."
      : "Stored once. Same bytes under any other name cost nothing.";
    receipt.append(title, dl, fpRow, verdict);
    live.textContent = duplicate
      ? name + " has the same bytes as a file already stored. Nothing was written."
      : name + " hashed and stored. Its name is the first sixteen characters " + hex.slice(0, 16) + ".";
  }

  function message(text) {
    receipt.textContent = "";
    const p = document.createElement("p");
    p.className = "verdict";
    p.textContent = text;
    receipt.append(p);
    live.textContent = text;
  }

  async function handle(file) {
    if (!file) return;
    if (!canHash) return message("Your browser blocked hashing on this page. It needs https or localhost.");
    if (file.size > LIMIT) return message("This demo stops at 100 MB to spare your phone's memory. Pick something smaller.");
    try {
      const started = performance.now();
      const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const ms = Math.max(1, Math.round(performance.now() - started));
      const hex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
      const names = stored.get(hex) || [];
      const duplicate = names.length > 0;
      names.push(file.name);
      stored.set(hex, names);
      render({ name: file.name, length: file.size, hex, ms, duplicate, names });
    } catch (e) {
      message("Could not read that file here. Try another.");
    }
  }

  input.addEventListener("change", () => handle(input.files[0]));
  logoBtn.addEventListener("click", async () => {
    try {
      const res = await fetch(logoBtn.dataset.src);
      const blob = await res.blob();
      await handle(new File([blob], "choud-logo-light.png", { type: blob.type }));
    } catch (e) {
      message("Could not load the logo here.");
    }
  });

  // dragging a file anywhere on the page must never navigate away from it
  ["dragenter", "dragover"].forEach((t) =>
    window.addEventListener(t, (e) => {
      if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes("Files")) return;
      e.preventDefault();
      drop.classList.add("over");
    }),
  );
  ["dragleave", "dragend"].forEach((t) =>
    window.addEventListener(t, (e) => {
      if (e.relatedTarget === null) drop.classList.remove("over");
    }),
  );
  window.addEventListener("drop", (e) => {
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes("Files")) return;
    e.preventDefault();
    drop.classList.remove("over");
    handle(e.dataTransfer.files[0]);
  });

  // the prefilled receipt is plain HTML; draw its fingerprint from the hash it carries
  const first = receipt.querySelector("canvas");
  if (first && LOGO_HASH) fingerprint(first, LOGO_HASH);
}
