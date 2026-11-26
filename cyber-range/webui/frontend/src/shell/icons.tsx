// UX-16: the console's line icon set (24 px grid, 1.8 stroke). Icons are
// decorative: every use sits next to a text label or carries aria-label on
// its button, so the SVG is hidden from assistive technology.
const PATHS = {
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm10 2-4.3-4.3",
  bell: "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9m4.3 13a1.9 1.9 0 0 0 3.4 0",
  agent:
    "M12 8V4H8m-2 4h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2zm-4 6h2m16 0h2M9 13v2m6-2v2",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0-15v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  x: "M18 6 6 18M6 6l12 12",
  arrow: "M5 12h14m-7-7 7 7-7 7",
  enter: "M9 10 4 15l5 5M20 4v7a4 4 0 0 1-4 4H4",
  back: "M19 12H5m7 7-7-7 7-7",
  updown: "m7 15 5 5 5-5M7 9l5-5 5 5",
  sparkles:
    "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9zM5 2l.6 1.4L7 4l-1.4.6L5 6l-.6-1.4L3 4l1.4-.6z",
  home: "M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  box: "M21 8v8l-9 5-9-5V8l9-5zm-9 13V12m9-4-9 4-9-4",
  plus: "M12 5v14M5 12h14",
  flag: "M4 22V4a1 1 0 0 1 1-1h14l-3 5 3 5H5",
  file: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zm0 0v6h6M8 13h8m-8 4h5",
  layers: "m12 2 10 5-10 5L2 7zm-10 10 10 5 10-5M2 17l10 5 10-5",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5",
  scale:
    "M12 3v18M5 7h14M5 7l-3 7a4 4 0 0 0 6 0zm14 0-3 7a4 4 0 0 0 6 0zM8 21h8",
  chart: "M3 3v18h18M7 15l4-5 3 3 5-7",
  target:
    "M12 22a10 10 0 1 1 0-20 10 10 0 0 1 0 20zm0-4a6 6 0 1 0 0-12 6 6 0 0 0 0 12zm0-4a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  server: "M4 4h16v6H4zm0 10h16v6H4zM8 7h.01M8 17h.01",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4m14-7-5-5-5 5m5-5v12",
  pulse: "M22 12h-4l-3 9L9 3l-3 9H2",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  swap: "M17 3l4 4-4 4M3 7h18M7 21l-4-4 4-4m14 4H3",
  term: "m4 17 6-6-6-6m8 14h8",
  globe:
    "M12 22a10 10 0 1 1 0-20 10 10 0 0 1 0 20zM2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20z",
  bolt: "M13 2 3 14h8l-1 8 10-12h-8z",
  link: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1m2 7a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1",
  key: "M15 7a4 4 0 1 1-3.9 5H8v3H5v3H2v-3l7.1-7.1A4 4 0 0 1 15 7z",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm8-3 2-1-2-4-2 1a7 7 0 0 0-2-1l-.5-2h-5L10 5a7 7 0 0 0-2 1L6 5 4 9l2 1a7 7 0 0 0 0 2l-2 1 2 4 2-1a7 7 0 0 0 2 1l.5 2h5l.5-2a7 7 0 0 0 2-1l2 1 2-4-2-1a7 7 0 0 0 0-2z",
  user: "M20 21a8 8 0 0 0-16 0M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  out: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5m5 5H9",
  clock: "M12 22a10 10 0 1 1 0-20 10 10 0 0 1 0 20zm0-16v6l4 2",
  wrench:
    "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 15 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
