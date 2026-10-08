import { useEffect, useId, useRef, useState } from "react";

export type MapNode = {
  name: string;
  kind: "foothold" | "target" | "host";
  detail?: string;
  state?: string;
};

export type MapSegment = { name: string; nodes: string[] };

import {
  HUB_WIDTH,
  NODE_WIDTH,
  layoutTopology,
  type TopologyLayout,
} from "./layout";

function shortLabel(value: string, length: number) {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

export function SegmentMap({
  nodes,
  segments,
  unsegmented = [],
  unavailable = false,
  selected,
  onSelect,
  compact = false,
}: {
  nodes: MapNode[];
  segments: MapSegment[];
  unsegmented?: string[];
  unavailable?: boolean;
  selected?: string;
  onSelect?: (name: string) => void;
  compact?: boolean;
}) {
  const mapId = useId();
  const frame = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(900);
  useEffect(() => {
    const element = frame.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setAvailable(Math.floor(entry.contentRect.width) - 2),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const byName = new Map(nodes.map((node) => [node.name, node]));
  const layout: TopologyLayout | null = layoutTopology(
    nodes,
    segments,
    available,
    compact,
  );
  const narrow = layout === null;
  const scroller = useRef<HTMLDivElement>(null);
  const [hidden, setHidden] = useState(0);
  useEffect(() => {
    const element = scroller.current;
    if (!element) return setHidden(0);
    const update = () =>
      setHidden(
        Math.max(
          0,
          element.scrollWidth - element.clientWidth - element.scrollLeft,
        ),
      );
    update();
    element.addEventListener("scroll", update, { passive: true });
    return () => element.removeEventListener("scroll", update);
  }, [layout?.width, available]);
  const linked = new Set(segments.flatMap((segment) => segment.nodes));
  const unlinked = [
    ...new Set([
      ...unsegmented,
      ...nodes
        .filter((node) => !linked.has(node.name))
        .map((node) => node.name),
    ]),
  ]
    .map((name) => byName.get(name))
    .filter((node): node is MapNode => Boolean(node));

  return (
    <div
      className={`segment-map${narrow ? " segment-map-narrow" : ""}`}
      ref={frame}
    >
      <div className="segment-map-heading">
        <span>DECLARED TOPOLOGY</span>
        <span>
          {nodes.length} {nodes.length === 1 ? "station" : "stations"} ·{" "}
          {segments.length} {segments.length === 1 ? "network" : "networks"}
        </span>
      </div>
      {!unavailable && segments.length > 0 ? (
        <>
          {layout && hidden > 4 && (
            <p className="topology-scroll-hint" aria-hidden="true">
              Map continues to the right. Scroll or tab through stations.
            </p>
          )}
          {layout && (
            <div
              className={`topology-graph-scroll${hidden > 4 ? " has-more" : ""}`}
              ref={scroller}
              tabIndex={hidden > 4 ? 0 : undefined}
              aria-label="Topology map, scrolls horizontally"
            >
              <svg
                className="topology-graph"
                viewBox={`0 0 ${layout.width} ${layout.height}`}
                width={layout.width}
                height={layout.height}
                role={onSelect ? "group" : "img"}
                aria-labelledby={`${mapId}-title ${mapId}-description`}
              >
                <title id={`${mapId}-title`}>Declared arena topology</title>
                <desc id={`${mapId}-description`}>
                  Stations connect to their declared network segments, ordered
                  by hop from the attacker foothold. Connections do not prove
                  live reachability.
                </desc>
                <defs>
                  <pattern
                    id="topology-grid"
                    width="26"
                    height="26"
                    patternUnits="userSpaceOnUse"
                  >
                    <path
                      d="M 26 0 L 0 0 0 26"
                      fill="none"
                      stroke="#b9a575"
                      strokeOpacity=".11"
                      strokeWidth="1"
                    />
                  </pattern>
                </defs>
                <rect
                  width={layout.width}
                  height={layout.height}
                  fill="url(#topology-grid)"
                />
                {layout.columns.map((column, index) => (
                  <text
                    key={index}
                    className="topology-column-label"
                    x={column.x + column.width / 2}
                    y="27"
                    textAnchor="middle"
                  >
                    {column.label}
                  </text>
                ))}
                {segments.flatMap((segment) => {
                  const hub = layout.hubs.get(segment.name);
                  if (!hub) return [];
                  return segment.nodes.map((name) => {
                    const station = layout.stations.get(name);
                    if (!station) return null;
                    const forward = hub.column > station.column;
                    const startX = forward ? station.x + NODE_WIDTH : station.x;
                    const endX = forward ? hub.x : hub.x + HUB_WIDTH;
                    const bend =
                      (forward ? 1 : -1) * Math.min(78, layout.gap * 0.8);
                    return (
                      <path
                        key={`${segment.name}:${name}`}
                        className="topology-edge"
                        d={`M ${startX} ${station.y} C ${startX + bend} ${station.y}, ${endX - bend} ${hub.y}, ${endX} ${hub.y}`}
                        pathLength="1"
                      />
                    );
                  });
                })}
                {segments.map((segment) => {
                  const hub = layout.hubs.get(segment.name);
                  if (!hub) return null;
                  const center = hub.x + HUB_WIDTH / 2;
                  return (
                    <g className="topology-hub" key={segment.name}>
                      <title>
                        Network {segment.name}: {segment.nodes.join(", ")}
                      </title>
                      <path
                        d={`M ${hub.x} ${hub.y - 29} H ${hub.x + HUB_WIDTH - 12} L ${hub.x + HUB_WIDTH} ${hub.y - 17} V ${hub.y + 29} H ${hub.x} Z`}
                      />
                      <circle cx={center} cy={hub.y - 8} r="5" />
                      <text x={center} y={hub.y + 13} textAnchor="middle">
                        {shortLabel(segment.name, 13)}
                      </text>
                    </g>
                  );
                })}
                {nodes.map((node, nodeIndex) => {
                  const position = layout.stations.get(node.name);
                  if (!position) return null;
                  const x = position.x;
                  const y = position.y;
                  return (
                    <g
                      className={`topology-station topology-station-${node.kind}${selected === node.name ? " selected" : ""}`}
                      key={node.name}
                      role={onSelect ? "button" : undefined}
                      tabIndex={onSelect ? 0 : undefined}
                      aria-labelledby={
                        onSelect
                          ? `${mapId}-station-${nodeIndex}-name ${mapId}-station-${nodeIndex}-detail${node.state ? ` ${mapId}-station-${nodeIndex}-state` : ""}`
                          : undefined
                      }
                      aria-pressed={
                        onSelect ? selected === node.name : undefined
                      }
                      onClick={() => onSelect?.(node.name)}
                      onKeyDown={(event) => {
                        if (
                          onSelect &&
                          (event.key === "Enter" || event.key === " ")
                        ) {
                          event.preventDefault();
                          onSelect(node.name);
                        }
                      }}
                    >
                      {!onSelect && (
                        <title>
                          {node.name}: {node.detail || node.kind}
                          {node.state ? `, ${node.state}` : ""}
                        </title>
                      )}
                      <path
                        d={`M ${x} ${y - 35} H ${x + NODE_WIDTH - 11} L ${x + NODE_WIDTH} ${y - 24} V ${y + 35} H ${x} Z`}
                      />
                      <path
                        className="topology-station-mark"
                        d={`M ${x + 15} ${y - 11} L ${x + 28} ${y - 23} L ${x + 41} ${y - 11} L ${x + 28} ${y + 1} Z`}
                      />
                      <text
                        id={`${mapId}-station-${nodeIndex}-name`}
                        className="topology-station-name"
                        x={x + 52}
                        y={y - 9}
                      >
                        {shortLabel(node.name, 16)}{" "}
                      </text>
                      <text
                        id={`${mapId}-station-${nodeIndex}-detail`}
                        className="topology-station-detail"
                        x={x + 52}
                        y={y + 11}
                      >
                        {shortLabel(node.detail || node.kind, 21)}{" "}
                      </text>
                      {node.state && (
                        <text
                          id={`${mapId}-station-${nodeIndex}-state`}
                          className="topology-station-state"
                          x={x + NODE_WIDTH - 12}
                          y={y + 27}
                          textAnchor="end"
                        >
                          {shortLabel(node.state, 16)}
                        </text>
                      )}
                    </g>
                  );
                })}
              </svg>
            </div>
          )}
          <div className="topology-mobile" aria-label="Network membership">
            {segments.map((hub) => (
              <div className="topology-mobile-network" key={hub.name}>
                <strong>◇ {hub.name}</strong>
                <div>
                  {hub.nodes
                    .map((name) => byName.get(name))
                    .filter((node): node is MapNode => Boolean(node))
                    .sort(
                      (first, second) =>
                        Number(second.kind === "foothold") -
                        Number(first.kind === "foothold"),
                    )
                    .map((node) => (
                      <span key={node.name}>
                        {node.name}
                        <small>
                          {node.kind === "foothold" ? "Attacker" : node.kind}
                        </small>
                      </span>
                    ))}
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="topology-unknown">
          <strong>Network links unavailable</strong>
          <span>
            This record has no topology recipe. Station relationships cannot be
            verified.
          </span>
          <div>
            {nodes.map((node) => (
              <span key={node.name}>{node.name}</span>
            ))}
          </div>
        </div>
      )}
      {unlinked.length > 0 && !unavailable && (
        <div className="topology-unlinked">
          <strong>No declared network</strong>
          {unlinked.map((node) => (
            <span key={node.name}>{node.name}</span>
          ))}
        </div>
      )}
      <p className="segment-map-note">
        Connections show declared membership, not observed reachability.
      </p>
    </div>
  );
}
