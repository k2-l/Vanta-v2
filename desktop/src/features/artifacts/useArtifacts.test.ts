import { describe, expect, it } from "vitest";
import type { ArtifactWire } from "@/contracts/resources";
import { previewKindFor } from "./useArtifacts";

function artifact(patch: Partial<ArtifactWire> = {}): ArtifactWire {
  return {
    id: "artifact-1",
    kind: "note",
    sensitivity: "internal",
    title: "Artifact",
    content: "body",
    ...patch,
  };
}

describe("artifact preview allowlist", () => {
  it("maps trusted text formats to their renderer", () => {
    expect(previewKindFor(artifact({ media_type: "text/markdown" }))).toBe("markdown");
    expect(previewKindFor(artifact({ media_type: "text/plain" }))).toBe("text");
    expect(previewKindFor(artifact({ media_type: "application/json" }))).toBe("code");
  });

  it("only previews allowlisted raster data URLs as images", () => {
    expect(
      previewKindFor(artifact({ media_type: "image/png", content: "data:image/png;base64,AA==" })),
    ).toBe("image");
    expect(
      previewKindFor(artifact({ media_type: "image/svg+xml", content: "data:image/svg+xml,<svg/>" })),
    ).toBe("none");
  });

  it("never previews secret or unknown content", () => {
    expect(previewKindFor(artifact({ sensitivity: "secret" }))).toBe("none");
    expect(previewKindFor(artifact({ kind: "binary", media_type: "application/octet-stream" }))).toBe("none");
  });
});
