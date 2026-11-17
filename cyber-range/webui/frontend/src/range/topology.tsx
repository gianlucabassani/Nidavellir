import type { TopologyData } from "../types";
import { SegmentMap } from "../topology/SegmentMap";

export function TopologyPreview({
  topology,
}: {
  topology: NonNullable<TopologyData["topology"]>;
}) {
  return (
    <>
      <SegmentMap
        nodes={topology.nodes.map((node) => ({
          name: node.name,
          kind:
            node.kind === "foothold"
              ? "foothold"
              : node.kind === "target"
                ? "target"
                : "host",
          detail: node.role || node.kind,
        }))}
        segments={topology.segments}
      />
      <div className="topology-facts">
        <span>{topology.segments.length} network segments</span>
        <span>Egress {topology.egress}</span>
      </div>
    </>
  );
}
