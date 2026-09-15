import { describe, expect, it } from "vitest";
import type { ApprovalWire } from "@/contracts/resources";
import { activeApprovalCount, isApprovalExpired } from "./useApprovals";

function approval(expiresAt?: string): ApprovalWire {
  return {
    call_id: "approval-1",
    tool_name: "shell",
    message: "Confirm action",
    session_id: "session-1",
    requested_at: "2026-09-15T12:00:00.000Z",
    expires_at: expiresAt ?? "",
  };
}

describe("approval expiry projection", () => {
  const now = Date.parse("2026-09-15T13:00:00.000Z");

  it("treats the exact expiry instant as expired", () => {
    expect(isApprovalExpired(approval("2026-09-15T13:00:00.000Z"), now)).toBe(true);
    expect(isApprovalExpired(approval("2026-09-15T13:00:00.001Z"), now)).toBe(false);
  });

  it("excludes expired rows from the global pending count", () => {
    expect(
      activeApprovalCount(
        [approval("2026-09-15T12:59:59.000Z"), approval("2026-09-15T14:00:00.000Z"), approval()],
        now,
      ),
    ).toBe(2);
  });
});
