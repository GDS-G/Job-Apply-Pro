import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("shows the Workbench safety boundary", () => {
    render(<App />);

    expect(
      screen.getByText("Candidate Knowledge v0.5.0-alpha.1"),
    ).toBeInTheDocument();
    expect(screen.getByText(/submission is disabled/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create encrypted profile/i }),
    ).toBeInTheDocument();
  });
});
