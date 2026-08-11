import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("shows the Core safety boundary", () => {
    render(<App />);

    expect(screen.getByText("Core v0.2.0-alpha.1")).toBeInTheDocument();
    expect(
      screen.getByText(/production submission are intentionally disabled/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /start discovery/i }),
    ).toBeInTheDocument();
  });
});
