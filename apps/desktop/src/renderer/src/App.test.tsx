import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("shows the Foundation safety boundary", () => {
    render(<App />);

    expect(screen.getByText("Foundation v0.1.0-alpha.1")).toBeInTheDocument();
    expect(
      screen.getByText(/production submission are intentionally disabled/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /start discovery/i }),
    ).toBeInTheDocument();
  });
});
