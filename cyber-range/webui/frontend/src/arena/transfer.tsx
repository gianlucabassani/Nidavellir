import { useRef, useState } from "react";
import { postJson } from "../api";
import type { ArenaData } from "../types";
import { Empty, Panel } from "../ui";

const MAX_FILE_BYTES = 1024 * 1024;
const CHUNK_BYTES = 262144;
type UploadReceipt = {
  uploaded: boolean;
  node: string;
  path?: string;
  bytes?: number;
  digest: string;
};
type DownloadChunk = {
  content_b64: string;
  offset: number;
  returned_bytes: number;
  file_bytes: number;
  next_offset: number | null;
  digest: string;
};

function base64(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 16384)
    binary += String.fromCharCode(...bytes.slice(index, index + 16384));
  return btoa(binary);
}
function bytesFromBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

export function TransferWorkbench({ arena }: { arena: ArenaData }) {
  const footholds = arena.nodes.filter((node) => node.foothold);
  const uploadFile = useRef<HTMLInputElement>(null);
  const [node, setNode] = useState(footholds[0]?.name || "");
  const [uploadPath, setUploadPath] = useState("");
  const [downloadPath, setDownloadPath] = useState("");
  const [receipt, setReceipt] = useState<UploadReceipt | null>(null);
  const [downloadReceipt, setDownloadReceipt] = useState<{
    bytes: number;
    digest: string;
  } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const endpoint = `/api/console/arenas/${encodeURIComponent(arena.id)}/files`;
  async function upload() {
    const file = uploadFile.current?.files?.[0];
    if (!file || !uploadPath.trim() || !node || pending) return;
    if (file.size > MAX_FILE_BYTES) {
      setError("Choose a file up to 1 MiB.");
      return;
    }
    setPending(true);
    setError("");
    setReceipt(null);
    try {
      const content = base64(new Uint8Array(await file.arrayBuffer()));
      const result = await postJson<UploadReceipt>(`${endpoint}/upload`, {
        node,
        path: uploadPath.trim(),
        content_b64: content,
      });
      setReceipt({ ...result, path: uploadPath.trim() });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setPending(false);
    }
  }
  async function download() {
    if (!downloadPath.trim() || !node || pending) return;
    setPending(true);
    setError("");
    setDownloadReceipt(null);
    try {
      const parts: Uint8Array[] = [];
      let offset = 0;
      let expectedBytes: number | null = null;
      let expectedDigest = "";
      while (true) {
        const chunk = await postJson<DownloadChunk>(`${endpoint}/download`, {
          node,
          path: downloadPath.trim(),
          offset,
          max_bytes: CHUNK_BYTES,
        });
        const bytes = bytesFromBase64(chunk.content_b64);
        if (
          chunk.offset !== offset ||
          bytes.length !== chunk.returned_bytes ||
          chunk.file_bytes > MAX_FILE_BYTES ||
          (expectedBytes !== null &&
            (chunk.file_bytes !== expectedBytes ||
              chunk.digest !== expectedDigest))
        )
          throw new Error(
            "The downloaded chunks did not match the service manifest.",
          );
        expectedBytes = chunk.file_bytes;
        expectedDigest = chunk.digest;
        parts.push(bytes);
        if (chunk.next_offset === null) break;
        if (chunk.next_offset <= offset || chunk.next_offset > MAX_FILE_BYTES)
          throw new Error("The service returned an invalid next offset.");
        offset = chunk.next_offset;
      }
      const joined = new Uint8Array(expectedBytes || 0);
      let position = 0;
      for (const part of parts) {
        joined.set(part, position);
        position += part.length;
      }
      if (position !== expectedBytes)
        throw new Error("The downloaded file is incomplete.");
      const digestBytes = new Uint8Array(
        await crypto.subtle.digest("SHA-256", joined),
      );
      const digest = `sha256:${Array.from(digestBytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
      if (digest !== expectedDigest)
        throw new Error("The downloaded file failed its SHA-256 check.");
      const url = URL.createObjectURL(new Blob([joined]));
      const link = document.createElement("a");
      link.href = url;
      link.download = downloadPath.split("/").at(-1) || "arena-file";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloadReceipt({ bytes: joined.length, digest });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Download failed");
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="transfer-grid">
      <Panel eyebrow="01 / FOOTHOLD TRANSFER" title="Upload file">
        <p className="scenario-description">
          Copy one file below the selected foothold's fixed transfer root. The
          console accepts files up to 1 MiB; the service rechecks path and
          scope.
        </p>
        {arena.state === "active" && footholds.length ? (
          <form
            className="setup-form transfer-form"
            onSubmit={(event) => {
              event.preventDefault();
              void upload();
            }}
          >
            <label>
              Foothold node
              <select
                value={node}
                onChange={(event) => setNode(event.target.value)}
              >
                {footholds.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Relative destination path
              <input
                value={uploadPath}
                required
                maxLength={512}
                onChange={(event) => {
                  setUploadPath(event.target.value);
                  setReceipt(null);
                }}
                placeholder="input/sample.txt"
              />
            </label>
            <label>
              Local file
              <input
                ref={uploadFile}
                type="file"
                required
                onChange={() => setReceipt(null)}
              />
            </label>
            <button className="button button-gold" disabled={pending}>
              {pending ? "Transferring…" : "Upload to foothold ↗"}
            </button>
          </form>
        ) : (
          <Empty
            title={arena.state !== "active" ? "Transfer closed" : "No foothold"}
            detail={
              arena.state !== "active"
                ? "File transfer stops with the arena."
                : "This arena has no transfer foothold."
            }
          />
        )}
        {receipt && (
          <div className="transfer-receipt" role="status">
            <strong>File uploaded</strong>
            <small>
              {receipt.node} · {receipt.bytes ?? "—"} bytes
            </small>
            <code>{receipt.digest}</code>
            <a
              href={`/console/arena/${encodeURIComponent(arena.id)}?tab=poc&file=${encodeURIComponent(receipt.path || "")}`}
              className="inline-action"
            >
              Select for PoC ↗
            </a>
          </div>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </Panel>
      <Panel eyebrow="02 / VERIFIED DOWNLOAD" title="Retrieve file">
        <p className="scenario-description">
          Read a foothold file in bounded chunks. Download begins only after the
          assembled bytes match the service's SHA-256 digest.
        </p>
        {arena.state === "active" && footholds.length ? (
          <form
            className="setup-form transfer-form"
            onSubmit={(event) => {
              event.preventDefault();
              void download();
            }}
          >
            <label>
              Foothold node
              <select
                value={node}
                onChange={(event) => setNode(event.target.value)}
              >
                {footholds.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Relative source path
              <input
                value={downloadPath}
                required
                maxLength={512}
                onChange={(event) => setDownloadPath(event.target.value)}
                placeholder="output/result.json"
              />
            </label>
            <button className="button button-outline" disabled={pending}>
              {pending ? "Verifying…" : "Verify and download ↗"}
            </button>
          </form>
        ) : (
          <Empty
            title="No live transfer"
            detail="Only active arenas with a foothold can serve files."
          />
        )}
        {downloadReceipt && (
          <div className="transfer-receipt" role="status">
            <strong>SHA-256 verified</strong>
            <small>{downloadReceipt.bytes} bytes downloaded</small>
            <code>{downloadReceipt.digest}</code>
          </div>
        )}
      </Panel>
    </div>
  );
}
