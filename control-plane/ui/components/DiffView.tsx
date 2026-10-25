import { Icon } from "./Icon";

interface Line {
  kind: "add" | "del" | "ctx" | "hunk";
  n: number | null;
  text: string;
}

// Renders a unified diff with line numbers (new-file numbers for added and context lines, old for removed).
export function parseDiff(diff: string): { file: string; lines: Line[] } {
  let file = "";
  let oldN = 0;
  let newN = 0;
  const lines: Line[] = [];
  for (const raw of diff.replace(/\n$/, "").split("\n")) {
    if (raw.startsWith("+++ ")) {
      file = raw.slice(4).replace(/^b\//, "");
    } else if (raw.startsWith("--- ")) {
      if (!file) file = raw.slice(4).replace(/^a\//, "");
    } else if (raw.startsWith("@@")) {
      const m = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/);
      oldN = m ? Number(m[1]) : 1;
      newN = m ? Number(m[2]) : 1;
      lines.push({ kind: "hunk", n: null, text: raw });
    } else if (raw.startsWith("+")) {
      lines.push({ kind: "add", n: newN++, text: raw.slice(1) });
    } else if (raw.startsWith("-")) {
      lines.push({ kind: "del", n: oldN++, text: raw.slice(1) });
    } else if (raw.startsWith("\\")) {
      continue;
    } else {
      lines.push({ kind: "ctx", n: newN++, text: raw.startsWith(" ") ? raw.slice(1) : raw });
      oldN++;
    }
  }
  return { file, lines };
}

export function DiffView({ diff }: { diff: string }) {
  const { file, lines } = parseDiff(diff);
  return (
    <div className="diff">
      <div className="file"><Icon n="description" size="xs" />{file || "Changed file"}</div>
      <div className="scroll">
        {lines.map((l, i) =>
          l.kind === "hunk" ? (
            <div className="hunk" key={i}>{l.text}</div>
          ) : (
            <div className={`l ${l.kind === "ctx" ? "" : l.kind}`} key={i}>
              <span className="n">{l.n}</span>
              <span className="m">{l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "}</span>
              {l.text}
            </div>
          ),
        )}
      </div>
    </div>
  );
}
