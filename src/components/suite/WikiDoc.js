function inlineParts(text) {
  const parts = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let last = 0;
  let match = pattern.exec(text);
  let key = 0;
  while (match) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("`")) parts.push(<code key={key} className="rounded bg-canvas px-1 py-0.5 text-[13px]">{token.slice(1, -1)}</code>);
    else if (token.startsWith("**")) parts.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else parts.push(<em key={key}>{token.slice(1, -1)}</em>);
    key += 1;
    last = match.index + token.length;
    match = pattern.exec(text);
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function WikiDoc({ text }) {
  const source = String(text || "");
  const blocks = [];
  let list = null;
  let code = null;
  let key = 0;

  function closeList() {
    if (!list) return;
    const Tag = list.kind;
    blocks.push(
      <Tag key={key} className={`${list.kind === "ol" ? "list-decimal" : "list-disc"} space-y-1 pl-5 text-sm text-ink`}>
        {list.items.map((item) => (
          <li key={item.key}>{inlineParts(item.text)}</li>
        ))}
      </Tag>,
    );
    key += 1;
    list = null;
  }

  function pushList(kind, line) {
    const text = line.replace(kind === "ol" ? /^\s*\d+\.\s+/ : /^\s*-\s+/, "");
    if (!list || list.kind !== kind) {
      closeList();
      list = { kind, items: [] };
    }
    list.items.push({ key: `${key}-${list.items.length}`, text });
  }

  for (const line of source.split("\n")) {
    if (line.trim().startsWith("```")) {
      closeList();
      if (code) {
        blocks.push(
          <pre key={key} className="overflow-x-auto whitespace-pre-wrap rounded-xl bg-canvas p-3 text-sm text-ink">
            {code.join("\n")}
          </pre>,
        );
        key += 1;
        code = null;
      } else {
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(line);
      continue;
    }
    if (/^####\s+/.test(line)) {
      closeList();
      blocks.push(<h4 key={key} className="text-sm font-semibold text-ink">{inlineParts(line.replace(/^####\s+/, ""))}</h4>);
    } else if (/^###\s+/.test(line)) {
      closeList();
      blocks.push(<h3 key={key} className="text-base font-semibold text-ink">{inlineParts(line.replace(/^###\s+/, ""))}</h3>);
    } else if (/^##\s+/.test(line)) {
      closeList();
      blocks.push(<h2 key={key} className="text-lg font-semibold text-ink">{inlineParts(line.replace(/^##\s+/, ""))}</h2>);
    } else if (/^---+$/.test(line.trim())) {
      closeList();
      blocks.push(<hr key={key} className="border-line" />);
    } else if (/^\s*-\s+/.test(line)) {
      pushList("ul", line);
      continue;
    } else if (/^\s*\d+\.\s+/.test(line)) {
      pushList("ol", line);
      continue;
    } else if (!line.trim()) {
      closeList();
    } else {
      closeList();
      blocks.push(<p key={key} className="text-sm leading-6 text-ink">{inlineParts(line)}</p>);
    }
    key += 1;
  }
  closeList();
  if (code) {
    blocks.push(
      <pre key={key} className="overflow-x-auto whitespace-pre-wrap rounded-xl bg-canvas p-3 text-sm text-ink">
        {code.join("\n")}
      </pre>,
    );
  }
  return <div className="space-y-3">{blocks}</div>;
}
