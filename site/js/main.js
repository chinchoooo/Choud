// Page basics: theme flip, copy buttons, the architecture notes, the stamp.

const root = document.documentElement;

document.getElementById("flip")?.addEventListener("click", () => {
  const dark = getComputedStyle(root).getPropertyValue("color-scheme").includes("dark");
  const next = dark ? "paper" : "ink";
  root.dataset.theme = next;
  try {
    localStorage.setItem("choud-theme", next);
  } catch (e) {
    /* private mode: the choice just is not remembered */
  }
});

document.querySelectorAll("[data-copy]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const target = document.getElementById(btn.dataset.copy);
    try {
      await navigator.clipboard.writeText(target.innerText.replace(/\s+#.*$/gm, "").trim());
      btn.textContent = "copied";
    } catch (e) {
      btn.textContent = "select it";
    }
    setTimeout(() => (btn.textContent = "copy"), 1600);
  });
});

// architecture: each box says what it owns
const notes = {
  clients: ["Browser, Android app, desktop client", "Talk only to the API, over Tailscale or your home network. They never reach the engine or the database."],
  caddy: ["Caddy, the front door", "The only thing that listens on a port. A second door serves public share links and can reach nothing else."],
  api: ["Python API (FastAPI)", "Accounts, permissions, versions, sharing and search. It decides who may do what, then asks the engine to move bytes."],
  db: ["PostgreSQL", "Metadata: who owns what, every version, share links, the search index. It never holds file bytes."],
  engine: ["C++ engine", "Hashing, storing by content, deduplication, assembling uploaded chunks. Only the API can reach it."],
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

// the stamp slams down once, when it scrolls into view
const stamp = document.getElementById("stamp");
if (stamp) {
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          stamp.classList.add("slam");
          io.disconnect();
        }
      },
      { threshold: 0.6 },
    );
    io.observe(stamp);
  } else {
    stamp.classList.add("slam");
  }
}
