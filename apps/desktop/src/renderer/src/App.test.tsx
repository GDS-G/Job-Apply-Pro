import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows the Workbench safety boundary", () => {
    render(<App />);

    expect(
      screen.getByText("Provider Configuration Control v0.18.0-alpha.1"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /production submission and provider writes are disabled/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/reference ATS vertical slice/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /challenge framework/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /communication & scheduling/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: /operations, recovery & licensing/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create verified backup/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /stage restore/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /schedule daily/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/application report/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /export diagnostics/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/updates are disabled for development builds/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create encrypted profile/i }),
    ).toBeInTheDocument();
  });

  it("has no serious automated accessibility violations", async () => {
    const { container } = render(<App />);
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });

    expect(
      result.violations.filter(({ impact }) =>
        ["serious", "critical"].includes(impact ?? ""),
      ),
    ).toEqual([]);
  });

  it("syncs connected provider messages and reports bounded counts", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listIntegrationHealth",
    ).mockResolvedValue([
      {
        provider: "GMAIL",
        status: "CONNECTED",
        message: "Provider adapter is connected",
        read_enabled: true,
        write_enabled: false,
        granted_scopes: ["gmail.readonly"],
      },
    ]);
    const sync = vi
      .spyOn(window.jobApplyPro.workbench, "syncProviderMessages")
      .mockResolvedValue({
        provider: "GMAIL",
        fetched_count: 2,
        imported_count: 1,
        duplicate_count: 1,
        record_ids: ["record-1", "record-1"],
      });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /sync messages/i }),
    );

    expect(sync).toHaveBeenCalledWith("GMAIL");
    expect(
      await screen.findByText(/fetched 2, imported 1, already present 1/i),
    ).toBeInTheDocument();
  });

  it("imports a reviewed provider configuration without exposing its contents", async () => {
    const importConfiguration = vi
      .spyOn(
        window.jobApplyPro.workbench,
        "selectAndImportProviderConfiguration",
      )
      .mockResolvedValue({
        source: "ENCRYPTED_DATABASE",
        providers: [
          {
            provider: "GMAIL",
            oauth_configured: true,
            requested_scopes: ["gmail.readonly"],
            read_enabled: true,
            write_enabled: false,
          },
        ],
        automatic_categories: [],
        updated_at: new Date(0).toISOString(),
      });

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /import provider config/i }),
    );

    expect(importConfiguration).toHaveBeenCalledOnce();
    expect(
      await screen.findByText(/configuration imported for 1 provider/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/gmail\.readonly/i)).not.toBeInTheDocument();
  });
});
