"use client";

import { useState, type ReactNode } from "react";
import { copyText } from "../lib/clipboard";

function inline(text: string): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^\s)]+\))/g;
  return text.split(pattern).map((part, index) => {
    if (part.startsWith("**") || part.startsWith("__")) return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={`${part}-${index}`}>{part.slice(1, -1)}</code>;
    if ((part.startsWith("*") && part.endsWith("*")) || (part.startsWith("_") && part.endsWith("_"))) return <em key={`${part}-${index}`}>{part.slice(1, -1)}</em>;
    const link = part.match(/^\[([^\]]+)\]\(([^\s)]+)\)$/);
    if (link) return <a key={`${part}-${index}`} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    return <span key={`${part}-${index}`}>{part}</span>;
  });
}

function tableCells(line: string) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function tableRow(line: string, key: string) {
  const cells = tableCells(line);
  return <tr key={key}>{cells.map((cell, index) => <td key={`${key}-${index}`}>{inline(cell)}</td>)}</tr>;
}

function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await copyText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };
  return <button type="button" className={`markdown-copy${copied ? " copied" : ""}`} onClick={() => void copy()} title={`${label} to clipboard`} aria-label={`${label} to clipboard`}>{copied ? "Copied" : label}</button>;
}

export function MarkdownContent({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }

    const fence = line.match(/^\s*```(.*)$/);
    if (fence) {
      const language = fence[1].trim();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) { code.push(lines[index]); index += 1; }
      index += 1;
      const source = code.join("\n");
      blocks.push(<div className="markdown-code-wrap" key={`code-${index}`}><CopyButton value={source} label="Copy code" /><pre><code className={language ? `language-${language}` : undefined}>{source}</code></pre></div>);
      continue;
    }

    const heading = line.match(/^\s*(#{1,6})\s+(.+)$/);
    if (heading) {
      const tag = `h${heading[1].length}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      const Heading = tag;
      blocks.push(<Heading key={`heading-${index}`}>{inline(heading[2])}</Heading>);
      index += 1;
      continue;
    }

    if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) { blocks.push(<hr key={`rule-${index}`} />); index += 1; continue; }

    if (line.includes("|") && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const headerCells = tableCells(line);
      index += 2;
      const rows: ReactNode[] = [];
      const rawRows: string[][] = [];
      while (index < lines.length && lines[index].includes("|")) { rawRows.push(tableCells(lines[index])); rows.push(tableRow(lines[index], `row-${index}`)); index += 1; }
      const tableText = [headerCells, ...rawRows].map((row) => row.join("\t")).join("\n");
      const isWide = headerCells.length > 5;
      blocks.push(<div className="markdown-table-container" key={`table-${index}`}><CopyButton value={tableText} label="Copy table" /><div className="markdown-table-wrap"><table style={isWide ? { whiteSpace: "nowrap" } : undefined}><thead><tr>{headerCells.map((cell, cellIndex) => <th key={`${cell}-${cellIndex}`}>{inline(cell)}</th>)}</tr></thead><tbody>{rows}</tbody></table></div></div>);
      continue;
    }

    const list = line.match(/^\s*([-*+])\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (list || ordered) {
      const orderedList = Boolean(ordered);
      const items: ReactNode[] = [];
      while (index < lines.length) {
        const match = orderedList ? lines[index].match(/^\s*\d+[.)]\s+(.+)$/) : lines[index].match(/^\s*[-*+]\s+(.+)$/);
        if (!match) break;
        items.push(<li key={`item-${index}`}>{inline(match[1])}</li>);
        index += 1;
      }
      blocks.push(orderedList ? <ol key={`list-${index}`}>{items}</ol> : <ul key={`list-${index}`}>{items}</ul>);
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) { quote.push(lines[index].replace(/^\s*>\s?/, "")); index += 1; }
      blocks.push(<blockquote key={`quote-${index}`}>{quote.map((part, quoteIndex) => <div key={`${part}-${quoteIndex}`}>{inline(part)}</div>)}</blockquote>);
      continue;
    }

    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^\s*(#{1,6})\s+/.test(lines[index]) && !/^\s*([-*+])\s+/.test(lines[index]) && !/^\s*\d+[.)]\s+/.test(lines[index]) && !/^\s*```/.test(lines[index])) { paragraph.push(lines[index]); index += 1; }
    blocks.push(<p key={`paragraph-${index}`}>{inline(paragraph.join(" "))}</p>);
  }

  return <div className="markdown-content">{blocks}</div>;
}
