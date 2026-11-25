import "./navigation.css";
export const categories = [
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
      { tab: "terminal", label: "Shell & logs" },
      { tab: "browser", label: "Browser" },
      { tab: "poc", label: "Confined PoC" },
      { tab: "transfer", label: "File transfer" },
      { tab: "forwards", label: "Service forwards" },
    ],
  },
  {
    id: "record",
    label: "Record",
    mark: "◈",
    items: [
      { tab: "findings", label: "Findings" },
      { tab: "evidence", label: "Evidence" },
      { tab: "score", label: "Score & trace" },
    ],
  },
];
// UX-03: every tool is a visible link in a persistent, grouped list: one
// click and plain Tab order, no hover flyouts or hidden menus.
export function ArenaNavigation({
  id,
  tab,
}: {
  id: string;
  tab: string | null;
}) {
  const href = (item: string) =>
    `/console/arena/${encodeURIComponent(id)}?tab=${item}`;
  return (
    <nav className="arena-tool-list" aria-label="Arena tools">
      <a
        className="arena-tool-overview"
        href={href("forge")}
        aria-current={tab === "forge" ? "page" : undefined}
      >
        <span aria-hidden="true">⬡</span> Arena overview
      </a>
      <a
        className="arena-tool-overview"
        href={href("live")}
        aria-current={tab === "live" ? "page" : undefined}
      >
        <span aria-hidden="true">◉</span> Agent live view
      </a>
      {categories.map((category) => (
        <section
          key={category.id}
          aria-labelledby={`arena-tools-${category.id}`}
        >
          <h2 id={`arena-tools-${category.id}`}>
            <span aria-hidden="true">{category.mark}</span> {category.label}
          </h2>
          <ul>
            {category.items.map((item) => (
              <li key={item.tab}>
                <a
                  href={href(item.tab)}
                  aria-current={tab === item.tab ? "page" : undefined}
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </nav>
  );
}
