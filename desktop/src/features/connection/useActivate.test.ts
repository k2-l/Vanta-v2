import { describe, expect, it } from "vitest";
import { queryBelongsToConnection } from "./useActivate";

describe("connection query isolation", () => {
  it("finds the connection id at any query-key depth used by desktop modules", () => {
    expect(queryBelongsToConnection(["sessions", "server-a"], "server-a")).toBe(true);
    expect(queryBelongsToConnection(["approvals", "history", "server-a"], "server-a")).toBe(true);
  });

  it("does not remove global or another server's cache", () => {
    expect(queryBelongsToConnection(["connections"], "server-a")).toBe(false);
    expect(queryBelongsToConnection(["runs", "server-b"], "server-a")).toBe(false);
  });
});
