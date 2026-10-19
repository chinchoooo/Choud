// Page basics: theme flip, copy buttons, the stamp.

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
