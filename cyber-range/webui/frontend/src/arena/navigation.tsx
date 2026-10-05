import { useRef, useState } from "react";
import "./navigation.css";
const categories = [
  {
    id: "prepare",
    label: "Prepare",
    mark: "◇",
    items: [
      { tab: "setup", label: "Target setup" },
      { tab: "access", label: "Agent access" },
      { tab: "infrastructure", label: "Infrastructure" },
    ],
  },
  {
    id: "investigate",
    label: "Investigate",
    mark: "⇄",
    items: [
      { tab: "http", label: "HTTP capture & replay" },
      { tab: "browser", label: "Browser" },
      { tab: "poc", label: "Confined PoC" },
      { tab: "transfer", label: "File transfer" },
    ],
  },
  {
    id: "record",
    label: "Record",
    mark: "◈",
    items: [
      { tab: "findings", label: "Findings" },
      { tab: "evidence", label: "Evidence" },
    ],
  },
];
export function ArenaNavigation({
  id,
  tab,
}: {
  id: string;
  tab: string | null;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const triggers = useRef<Record<string, HTMLButtonElement | null>>({});
  return (
    <nav
      className="arena-tool-rail"
      aria-label="Arena tooling"
      onMouseLeave={() => setOpen(pinned)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(pinned);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          const active = open;
          if (active) triggers.current[active]?.focus();
          setOpen(null);
          setPinned(null);
          event.preventDefault();
        }
      }}
    >
      <a
        className="arena-rail-overview"
        href={`/console/arena/${encodeURIComponent(id)}`}
        aria-current={tab === "forge" ? "page" : undefined}
      >
        <span aria-hidden="true">⬡</span>
        <small>Arena</small>
      </a>
      {categories.map((category) => (
        <div
          className="arena-rail-category"
          key={category.id}
          onMouseEnter={() => setOpen(category.id)}
        >
          <button
            ref={(element) => {
              triggers.current[category.id] = element;
            }}
            type="button"
            onFocus={() => setOpen(category.id)}
            onClick={() => {
              const next = pinned === category.id ? null : category.id;
              setPinned(next);
              setOpen(next);
            }}
            aria-expanded={open === category.id}
            aria-controls={`arena-menu-${category.id}`}
            className={
              category.items.some((item) => item.tab === tab) ? "active" : ""
            }
          >
            <span aria-hidden="true">{category.mark}</span>
            <small>{category.label}</small>
          </button>
          {open === category.id && (
            <div
              className="arena-category-flyout"
              id={`arena-menu-${category.id}`}
            >
              <strong>{category.label}</strong>
              {category.items.map((item) => (
                <a
                  key={item.tab}
                  href={`/console/arena/${encodeURIComponent(id)}?tab=${item.tab}`}
                  aria-current={tab === item.tab ? "page" : undefined}
                  onClick={() => {
                    setOpen(null);
                    setPinned(null);
                  }}
                >
                  {item.label}
                  <span aria-hidden="true">↗</span>
                </a>
              ))}
            </div>
          )}
        </div>
      ))}
    </nav>
  );
}
