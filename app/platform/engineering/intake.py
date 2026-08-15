"""Extract text from uploaded engineering documents without extra packages."""
from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".tf", ".hcl", ".yml", ".yaml", ".json",
    ".py", ".toml", ".ini", ".cfg", ".env", ".gitignore", ".dockerfile",
    ".sh", ".ps1", ".xml", ".csv", ".bicep", ".rego",
}

KIND_BY_SUFFIX = {
    ".tf": "terraform",
    ".hcl": "terraform",
    ".bicep": "bicep",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".md": "document",
    ".txt": "document",
    ".pdf": "document",
    ".docx": "document",
    ".py": "python",
}


def infer_kind(filename: str, mime: str = "") -> str:
    lower = (filename or "").lower()
    for suffix, kind in KIND_BY_SUFFIX.items():
        if lower.endswith(suffix):
            return kind
    if "dockerfile" in lower:
        return "docker"
    if "workflow" in lower or lower.endswith(".yml"):
        return "cicd"
    if mime.startswith("image/"):
        return "diagram"
    return "document"


def extract_text(filename: str, data: bytes, mime: str = "") -> str:
    name = (filename or "").lower()
    if name.endswith(".docx"):
        return _docx_text(data)
    if name.endswith(".pdf"):
        return _pdf_text(data)
    if any(name.endswith(suffix) for suffix in TEXT_SUFFIXES) or mime.startswith("text/"):
        return data.decode("utf-8", errors="replace")[:200_000]
    if b"\x00" not in data[:2048]:
        return data.decode("utf-8", errors="replace")[:200_000]
    return f"(binary file {filename}, {len(data)} bytes — metadata stored, content not extracted)"


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        tree = ElementTree.fromstring(xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        parts = [node.text or "" for node in tree.findall(".//w:t", ns)]
        return "\n".join(part for part in parts if part).strip()[:200_000]
    except Exception:
        return "(could not parse DOCX)"


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages[:40]:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages).strip()
        return text[:200_000] if text else "(PDF had no extractable text)"
    except Exception:
        return "(PDF stored — install pypdf on the API image to extract text)"
