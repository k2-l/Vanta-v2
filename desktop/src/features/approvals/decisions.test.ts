import { describe, expect, it } from "vitest";
import { purgeLegacyApprovalStorage } from "./decisions";

describe("legacy approval storage cleanup", () => {
  it("removes sensitive approval records for every connection and preserves other settings", () => {
    const values = new Map([
      ["vanta.approvals.decisions.conn-a", JSON.stringify({ message: "secret A" })],
      ["vanta.approvals.decisions.conn-b", JSON.stringify({ message: "secret B" })],
      ["vanta.theme", "dark"],
    ]);
    const storage = {
      get length() { return values.size; },
      key(index: number) { return [...values.keys()][index] ?? null; },
      removeItem(key: string) { values.delete(key); },
    };

    purgeLegacyApprovalStorage(storage);

    expect([...values.entries()]).toEqual([["vanta.theme", "dark"]]);
  });
});
