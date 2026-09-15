import { describe, expect, it } from "vitest";
import { moduleFromPath, modulePath } from "./moduleNavigation";

describe("module routing", () => {
  it("maps every desktop module to a stable path", () => {
    expect(modulePath("chat")).toBe("/chat");
    expect(modulePath("artifacts")).toBe("/artifacts");
  });

  it("rejects unknown paths instead of silently selecting the wrong module", () => {
    expect(moduleFromPath("/runs/detail")).toBe("runs");
    expect(moduleFromPath("/legacy-dashboard")).toBeUndefined();
  });
});
