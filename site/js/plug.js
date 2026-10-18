// Pull the plug: two disks, one power cut. A simplified animation of the rule the storage engine
// follows (write to a temporary name, flush, rename, flush the folder).

const root = document.querySelector("[data-plug]");

if (root) {
  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TOTAL = 24;
  const TICK = still ? 40 : 230;
  const btn = root.querySelector("#plug-btn");
  const again = root.querySelector("#plug-reset");
  const a = root.querySelector("#disk-a");
  const b = root.querySelector("#disk-b");
  let state = "idle";
  let written = 0;
  let timer = null;

  const cells = (disk) => {
    const holder = disk.querySelector("[data-blocks]");
    if (!holder.children.length) {
      for (let n = 0; n < TOTAL; n++) holder.appendChild(document.createElement("i"));
    }
    return holder.children;
  };
  const say = (disk, status, result) => {
    disk.querySelector("[data-status]").textContent = status;
    disk.querySelector("[data-result]").textContent = result || "";
  };
  const setSteps = (n) => {
    root.querySelectorAll("[data-steps] li").forEach((li, k) => {
      li.className = k < n ? "done" : k === n ? "now" : "";
    });
  };
  const fillAll = (disk, cls) => {
    for (const c of cells(disk)) c.className = cls;
  };

  function reset() {
    clearInterval(timer);
    state = "idle";
    written = 0;
    fillAll(a, "old");
    fillAll(b, "old");
    say(a, "report.pdf (old copy) is on the disk", "");
    say(b, "report.pdf (old copy) is on the disk", "");
    setSteps(0);
    btn.textContent = "Start saving report.pdf";
    btn.classList.remove("danger");
    btn.disabled = false;
    again.hidden = true;
  }

  function frame() {
    if (state !== "writing") return;
    const ac = cells(a);
    const bc = cells(b);
    if (written < TOTAL) {
      ac[written].className = "new"; // the plain app overwrites the old bytes in place
      bc[written].className = "tmp"; // Choud fills a separate temporary file instead
      written++;
      say(a, "saving: " + written + " of " + TOTAL + " blocks", "");
      say(b, "writing report.pdf.tmp: " + written + " of " + TOTAL + " blocks", "");
      return;
    }
    clearInterval(timer);
    state = "done";
    fillAll(a, "new");
    fillAll(b, "new");
    setSteps(4);
    const late = "Too slow, it finished. Try again and pull the plug earlier.";
    say(a, "saved", late);
    say(b, "saved, renamed and flushed", late);
    btn.textContent = "Saved";
    btn.classList.remove("danger");
    btn.disabled = true;
    again.hidden = false;
  }

  function pull() {
    clearInterval(timer);
    state = "cut";
    document.body.classList.add("blackout");
    setTimeout(
      () => {
        document.body.classList.remove("blackout");
        const ac = cells(a);
        for (let n = 0; n < written; n++) ac[n].className = "new";
        for (let m = written; m < TOTAL; m++) ac[m].className = "old";
        say(
          a,
          "power lost after " + written + " of " + TOTAL + " blocks",
          written > 0
            ? "After reboot: " + written + " blocks of the new file glued to " + (TOTAL - written) + " blocks of the old one. report.pdf will not open."
            : "After reboot: nothing was written.",
        );
        fillAll(b, "old");
        setSteps(0);
        say(
          b,
          "power lost after " + written + " of " + TOTAL + " blocks",
          "After reboot: removed 1 unfinished temporary file. report.pdf is the old copy, complete and intact. 0 half-written files.",
        );
        btn.textContent = "Power lost";
        btn.classList.remove("danger");
        btn.disabled = true;
        again.hidden = false;
      },
      still ? 150 : 700,
    );
  }

  reset();
  btn.addEventListener("click", () => {
    if (state === "idle") {
      state = "writing";
      btn.textContent = "PULL THE PLUG";
      btn.classList.add("danger");
      timer = setInterval(frame, TICK);
    } else if (state === "writing") {
      pull();
    }
  });
  again.addEventListener("click", reset);
}
