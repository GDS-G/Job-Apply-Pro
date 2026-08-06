import type { DesktopUpdateStatus } from "@job-apply-pro/contracts";

export function safeUpdateErrorMessage(error: unknown): string {
  const message =
    error instanceof Error ? error.message : "Update operation failed.";
  return message.replace(/https?:\/\/\S+/gi, "[redacted-url]").slice(0, 500);
}

export function initialUpdateStatus(
  packaged: boolean,
  currentVersion: string,
  checkedAt = new Date().toISOString(),
): DesktopUpdateStatus {
  return {
    state: packaged ? "IDLE" : "DISABLED",
    current_version: currentVersion,
    message: packaged
      ? "Secure update checks are available."
      : "Updates are disabled for development builds.",
    checked_at: checkedAt,
  };
}
