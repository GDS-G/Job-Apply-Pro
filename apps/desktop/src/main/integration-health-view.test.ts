import { describe, expect, it } from "vitest";

import { integrationHealthForRenderer } from "./integration-health-view.js";

describe("renderer integration health boundary", () => {
  it("removes credential references without mutating backend health", () => {
    const backend = [
      {
        provider: "GOOGLE_CALENDAR" as const,
        status: "CONNECTED" as const,
        message: "Connected",
        read_enabled: true,
        write_enabled: true,
        credential_reference: "private-main-process-handle",
        granted_scopes: ["calendar.events"],
        account_hint: "candidate@example.invalid",
      },
    ];

    const renderer = integrationHealthForRenderer(backend);

    expect(renderer).toEqual([
      {
        provider: "GOOGLE_CALENDAR",
        status: "CONNECTED",
        message: "Connected",
        read_enabled: true,
        write_enabled: true,
        granted_scopes: ["calendar.events"],
        account_hint: "candidate@example.invalid",
      },
    ]);
    expect("credential_reference" in renderer[0]!).toBe(false);
    expect(backend[0]!.credential_reference).toBe(
      "private-main-process-handle",
    );
    expect(renderer[0]).not.toBe(backend[0]);
    expect(renderer[0]!.granted_scopes).not.toBe(backend[0]!.granted_scopes);
  });
});
