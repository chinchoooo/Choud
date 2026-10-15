import { useEffect, useRef, useState } from "react";

export interface MenuItem {
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

/** A small "⋯" menu. Closes on outside click or Esc; items are real buttons for keyboards. */
export function RowMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        className="px-2 py-1 text-gray-600 hover:bg-gray-100 rounded-md"
      >
        ⋯
      </button>
      {open && (
        <ul
          role="menu"
          className="absolute right-0 z-30 mt-1 min-w-36 border border-gray-300 bg-white py-1 text-sm shadow-lg rounded-md"
        >
          {items.map((item) => (
            <li key={item.label} role="none">
              <button
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  item.onSelect();
                }}
                className={`block w-full px-3 py-1.5 text-left hover:bg-gray-100 ${
                  item.danger ? "text-red-600" : "text-gray-800"
                }`}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
