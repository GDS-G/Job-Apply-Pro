import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MediaCleanupPublicRecord } from "@job-apply-pro/contracts";

import { MediaCleanupPanel } from "./MediaCleanupPanel";

const confirmation = "I VERIFIED PROVIDER MEDIA CLEANUP";
const record: MediaCleanupPublicRecord = {
  id: "d94b9b5d-165c-4dd8-91d1-fd1b4bcfe6e2",
  provider_id: "gemini",
  state: "MANUAL_REVIEW",
  known_resource: false,
  attempts: 0,
  reason: "UNKNOWN_UPLOAD",
  lease_until: null,
  next_attempt_at: null,
  created_at: "2026-09-12T12:00:00.000001+00:00",
  updated_at: "2026-09-12T12:01:00.123456+00:00",
};

const pending: MediaCleanupPublicRecord = {
  ...record,
  id: "9ff4d9c2-050d-4c28-b50c-0583dfae26de",
  state: "DELETE_PENDING",
  known_resource: true,
  attempts: 2,
  reason: "DELETION_REQUIRED",
  next_attempt_at: "2026-09-12T13:00:00+00:00",
};

describe("MediaCleanupPanel", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("refreshes read-only and distinguishes manual unknown resources from automatic cleanup", async () => {
    const list = vi
      .spyOn(window.jobApplyPro.workbench, "listMediaCleanup")
      .mockResolvedValue({ items: [record, pending] });
    const retry = vi.spyOn(window.jobApplyPro.workbench, "retryMediaCleanup");
    const resolve = vi.spyOn(
      window.jobApplyPro.workbench,
      "resolveMediaCleanup",
    );
    render(<MediaCleanupPanel backendReady />);

    expect(
      await screen.findByText("Gemini · Unknown resource — manual review"),
    ).toBeInTheDocument();
    expect(screen.getByText("Gemini · Deletion pending")).toBeInTheDocument();
    expect(
      screen.getByText(/does not upload media or run a model/),
    ).toBeInTheDocument();
    expect(screen.getByText(/original provider credentials/)).toHaveTextContent(
      "A different configured account will not be used for deletion.",
    );
    expect(
      screen.getAllByRole("button", { name: "Review manual cleanup" }),
    ).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh media cleanup" }),
    );
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(retry).not.toHaveBeenCalled();
    expect(resolve).not.toHaveBeenCalled();
  });

  it("retries deletion through only the dedicated retry method", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listMediaCleanup",
    ).mockResolvedValue({ items: [pending] });
    const retry = vi
      .spyOn(window.jobApplyPro.workbench, "retryMediaCleanup")
      .mockResolvedValue({ items: [pending] });
    const resolve = vi.spyOn(
      window.jobApplyPro.workbench,
      "resolveMediaCleanup",
    );
    render(<MediaCleanupPanel backendReady />);
    await screen.findByText("Gemini · Deletion pending");
    fireEvent.click(
      screen.getByRole("button", { name: "Retry automatic deletion" }),
    );
    expect(
      await screen.findByText(/Deletion-only recovery pass finished/),
    ).toBeInTheDocument();
    expect(retry).toHaveBeenCalledExactlyOnceWith();
    expect(resolve).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Review manual cleanup" }),
    ).not.toBeInTheDocument();
  });

  it("allows recovery of an unknown upload lease without offering manual acknowledgement yet", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listMediaCleanup",
    ).mockResolvedValue({
      items: [
        { ...record, state: "UPLOADING", lease_until: record.updated_at },
      ],
    });
    const retry = vi
      .spyOn(window.jobApplyPro.workbench, "retryMediaCleanup")
      .mockResolvedValue({ items: [record] });
    render(<MediaCleanupPanel backendReady />);
    await screen.findByText("Gemini · Active lease / awaiting recovery");
    expect(
      screen.getByText(/Recovery respects the active lease/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Review manual cleanup" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry automatic deletion" }),
    );
    expect(
      await screen.findByText("Gemini · Unknown resource — manual review"),
    ).toBeInTheDocument();
    expect(retry).toHaveBeenCalledExactlyOnceWith();
  });

  it("requires the exact phrase and sends the displayed revision without claiming provider deletion", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listMediaCleanup",
    ).mockResolvedValue({ items: [record] });
    const resolve = vi
      .spyOn(window.jobApplyPro.workbench, "resolveMediaCleanup")
      .mockResolvedValue({ items: [] });
    render(<MediaCleanupPanel backendReady />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Review manual cleanup" }),
    );
    const input = screen.getByLabelText(`Type ${confirmation}`);
    const submit = screen.getByRole("button", {
      name: "Record operator acknowledgement",
    });
    for (const invalid of [
      "",
      confirmation.toLowerCase(),
      `${confirmation} `,
      ` ${confirmation}`,
    ]) {
      fireEvent.change(input, { target: { value: invalid } });
      expect(submit).toBeDisabled();
      fireEvent.submit(input.closest("form")!);
      expect(resolve).not.toHaveBeenCalled();
    }
    fireEvent.change(input, { target: { value: confirmation } });
    fireEvent.click(submit);
    expect(
      await screen.findByText(
        /Operator acknowledgement recorded. This does not independently confirm remote deletion/,
      ),
    ).toBeInTheDocument();
    expect(resolve).toHaveBeenCalledExactlyOnceWith(
      record.id,
      record.updated_at,
      confirmation,
    );
    expect(
      screen.getByText("No unresolved media cleanup records."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/successfully deleted/i)).not.toBeInTheDocument();
  });

  it("clears acknowledgement on refresh and uses only the latest revision", async () => {
    const updated = {
      ...record,
      updated_at: "2026-09-12T12:02:00.654321+00:00",
    };
    vi.spyOn(window.jobApplyPro.workbench, "listMediaCleanup")
      .mockResolvedValueOnce({ items: [record] })
      .mockResolvedValue({ items: [updated] });
    const resolve = vi
      .spyOn(window.jobApplyPro.workbench, "resolveMediaCleanup")
      .mockResolvedValue({ items: [] });
    render(<MediaCleanupPanel backendReady />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Review manual cleanup" }),
    );
    fireEvent.change(screen.getByLabelText(`Type ${confirmation}`), {
      target: { value: confirmation },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh media cleanup" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Review manual cleanup" }),
      ).toBeEnabled(),
    );
    expect(
      screen.queryByLabelText(`Type ${confirmation}`),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Review manual cleanup" }),
    );
    expect(screen.getByLabelText(`Type ${confirmation}`)).toHaveValue("");
    fireEvent.change(screen.getByLabelText(`Type ${confirmation}`), {
      target: { value: confirmation },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record operator acknowledgement" }),
    );
    await waitFor(() =>
      expect(resolve).toHaveBeenCalledExactlyOnceWith(
        updated.id,
        updated.updated_at,
        confirmation,
      ),
    );
  });

  it("requires a new refresh after failed or stale acknowledgement and hides private errors", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listMediaCleanup",
    ).mockResolvedValue({ items: [record] });
    vi.spyOn(
      window.jobApplyPro.workbench,
      "resolveMediaCleanup",
    ).mockRejectedValue(new Error("files/private-resource secret-token"));
    render(<MediaCleanupPanel backendReady />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Review manual cleanup" }),
    );
    fireEvent.change(screen.getByLabelText(`Type ${confirmation}`), {
      target: { value: confirmation },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Record operator acknowledgement" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The record may have changed",
    );
    expect(
      screen.getByRole("button", { name: "Review manual cleanup" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Refresh media cleanup" }),
    ).toBeEnabled();
    expect(
      screen.queryByText(/private-resource|secret-token/),
    ).not.toBeInTheDocument();
  });

  it("never renders arbitrary provider reasons or extra private fields", async () => {
    const privateRecord = {
      ...record,
      provider_id: "files/private-account",
      reason: "https://provider.example/private-uri secret-token",
      resource_name: "files/private-upload",
    };
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listMediaCleanup",
    ).mockResolvedValue({ items: [privateRecord] });
    render(<MediaCleanupPanel backendReady />);
    expect(
      await screen.findByText(
        "Configured provider · Unknown resource — manual review",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        /private-account|private-uri|secret-token|private-upload/,
      ),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry automatic deletion" }),
    ).toBeDisabled();
  });

  it("preserves unreadable known-resource records without offering an unsupported acknowledgement", async () => {
    vi.spyOn(
      window.jobApplyPro.workbench,
      "listMediaCleanup",
    ).mockResolvedValue({
      items: [
        { ...record, known_resource: true, reason: "UNREADABLE_RESOURCE" },
      ],
    });
    const resolve = vi.spyOn(
      window.jobApplyPro.workbench,
      "resolveMediaCleanup",
    );
    render(<MediaCleanupPanel backendReady />);
    expect(
      await screen.findByText(
        /Encrypted recovery metadata requires operator repair or restore support/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/This record is retained and cannot be acknowledged/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Review manual cleanup" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Record operator acknowledgement" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry automatic deletion" }),
    ).toBeDisabled();
    expect(resolve).not.toHaveBeenCalled();
  });

  it("waits for the backend and disables mutations during an in-flight refresh", async () => {
    let finish!: (value: { items: MediaCleanupPublicRecord[] }) => void;
    const list = vi
      .spyOn(window.jobApplyPro.workbench, "listMediaCleanup")
      .mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
    const { rerender } = render(<MediaCleanupPanel backendReady={false} />);
    expect(list).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Refresh media cleanup" }),
    ).toBeDisabled();
    rerender(<MediaCleanupPanel backendReady />);
    expect(
      screen.getByRole("button", { name: "Refresh media cleanup" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Retry automatic deletion" }),
    ).toBeDisabled();
    finish({ items: [pending] });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Retry automatic deletion" }),
      ).toBeEnabled(),
    );
    expect(list).toHaveBeenCalledTimes(1);
  });
});
