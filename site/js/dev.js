// Developer page: each architecture box says what it owns.

const notes = {
  clients: ["Browser, Android app, desktop client", "Talk only to the API, over Tailscale or your home network. They never reach the engine or the database."],
  caddy: ["Caddy, the front door", "The only thing that listens on a port. A second door serves public share links and can reach nothing else."],
  api: ["Python API (FastAPI)", "Accounts, permissions, versions, sharing and search. It decides who may do what, then asks the engine to move bytes."],
  db: ["PostgreSQL", "Metadata: who owns what, every version, share links, the search index, and the reference counts that decide when an object may be deleted. It never holds file bytes."],
  engine: ["C++ engine", "Hashing, storing by content, deduplication, assembling uploaded chunks. Only the API can reach it, over an internal network."],
  disk: ["Your disk", "Files sit at objects/<first two hex>/<hash>. Written to a temporary name, flushed, renamed, flushed again."],
};

const out = document.getElementById("arch-note");
document.querySelectorAll("[data-note]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("[data-note]").forEach((b) => b.setAttribute("aria-pressed", "false"));
    btn.setAttribute("aria-pressed", "true");
    const [title, body] = notes[btn.dataset.note];
    out.querySelector("h3").textContent = title;
    out.querySelector("p").textContent = body;
  });
});
