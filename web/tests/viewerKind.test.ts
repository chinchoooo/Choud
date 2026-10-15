import { describe, expect, it } from "vitest";

import { typeBadge, viewerKind } from "../src/lib/viewerKind";

const kind = (name: string, mime: string | null) => viewerKind({ name, mime_type: mime });

describe("viewerKind", () => {
  it("uses the built-in viewers for standard formats", () => {
    expect(kind("a.jpg", "image/jpeg")).toBe("image");
    expect(kind("a.mp4", "video/mp4")).toBe("video");
    expect(kind("a.mp3", "audio/mpeg")).toBe("audio");
    expect(kind("a.pdf", "application/pdf")).toBe("pdf");
    expect(kind("notes.txt", "text/plain")).toBe("text");
  });

  it("falls back on the extension when the type is missing or generic", () => {
    expect(kind("photo.PNG", "application/octet-stream")).toBe("image");
    expect(kind("clip.webm", null)).toBe("video");
    expect(kind("main.py", null)).toBe("text");
    expect(kind("data.json", "application/json")).toBe("text");
  });

  it("never renders SVG or HTML: SVG is a download, HTML shows as escaped source", () => {
    expect(kind("logo.svg", "image/svg+xml")).toBe("other");
    expect(kind("page.html", "text/html")).toBe("text");
  });

  it("offers a download for everything else", () => {
    expect(kind("archive.zip", "application/zip")).toBe("other");
    expect(kind("README", null)).toBe("other");
  });

  it("makes short type badges", () => {
    expect(typeBadge({ name: "x.pdf" })).toBe("PDF");
    expect(typeBadge({ name: "archive.tar.gz" })).toBe("GZ");
    expect(typeBadge({ name: "Makefile" })).toBe("FILE");
  });
});
