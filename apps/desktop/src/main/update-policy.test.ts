import { describe, expect, it } from "vitest";

import {
  initialUpdateStatus,
  safeUpdateErrorMessage,
} from "./update-policy.js";

describe("update policy", () => {
  it("redacts release URLs and bounds update errors", () => {
    const message = safeUpdateErrorMessage(
      new Error(
        `Download failed at https://releases.example.invalid/token/${"x".repeat(700)}`,
      ),
    );

    expect(message).not.toContain("example.invalid");
    expect(message).not.toContain("token");
    expect(message).toContain("[redacted-url]");
    expect(message.length).toBeLessThanOrEqual(500);
  });

  it("disables updates outside a packaged application", () => {
    expect(
      initialUpdateStatus(false, "0.20.0-alpha.1", "2026-08-06T00:00:00Z"),
    ).toEqual({
      state: "DISABLED",
      current_version: "0.20.0-alpha.1",
      message: "Updates are disabled for development builds.",
      checked_at: "2026-08-06T00:00:00Z",
    });
    expect(initialUpdateStatus(true, "0.20.0-alpha.1").state).toBe("IDLE");
  });
});
