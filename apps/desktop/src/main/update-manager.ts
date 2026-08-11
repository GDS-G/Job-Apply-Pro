import electronUpdater from "electron-updater";

import type { DesktopUpdateStatus } from "@job-apply-pro/contracts";

import {
  initialUpdateStatus,
  safeUpdateErrorMessage,
} from "./update-policy.js";

const { autoUpdater } = electronUpdater;
type UpdateListener = (status: DesktopUpdateStatus) => void;

export class UpdateManager {
  private listeners = new Set<UpdateListener>();
  private current: DesktopUpdateStatus;

  constructor(
    private readonly packaged: boolean,
    currentVersion: string,
  ) {
    this.current = initialUpdateStatus(packaged, currentVersion);
    if (!packaged) return;

    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = false;
    autoUpdater.allowPrerelease = true;
    autoUpdater.allowDowngrade = false;
    autoUpdater.on("checking-for-update", () =>
      this.update("CHECKING", "Checking the signed release channel…"),
    );
    autoUpdater.on("update-available", (info) =>
      this.update("AVAILABLE", `Version ${info.version} is available.`, {
        available_version: info.version,
      }),
    );
    autoUpdater.on("update-not-available", () =>
      this.update("UP_TO_DATE", "Job Apply Pro is up to date."),
    );
    autoUpdater.on("download-progress", (progress) =>
      this.update(
        "DOWNLOADING",
        `Downloading ${progress.percent.toFixed(0)}%…`,
        {
          progress_percent: progress.percent,
        },
      ),
    );
    autoUpdater.on("update-downloaded", (info) =>
      this.update(
        "DOWNLOADED",
        `Version ${info.version} is ready to install.`,
        {
          available_version: info.version,
          progress_percent: 100,
        },
      ),
    );
    autoUpdater.on("error", (error) =>
      this.update("ERROR", safeUpdateErrorMessage(error)),
    );
  }

  get status(): DesktopUpdateStatus {
    return this.current;
  }

  onStatus(listener: UpdateListener): () => void {
    this.listeners.add(listener);
    listener(this.current);
    return () => this.listeners.delete(listener);
  }

  async check(): Promise<DesktopUpdateStatus> {
    if (!this.packaged) return this.current;
    try {
      await autoUpdater.checkForUpdates();
    } catch (error) {
      this.update("ERROR", safeUpdateErrorMessage(error));
    }
    return this.current;
  }

  async download(): Promise<DesktopUpdateStatus> {
    if (!this.packaged || this.current.state !== "AVAILABLE")
      return this.current;
    try {
      await autoUpdater.downloadUpdate();
    } catch (error) {
      this.update("ERROR", safeUpdateErrorMessage(error));
    }
    return this.current;
  }

  install(): void {
    if (this.packaged && this.current.state === "DOWNLOADED") {
      autoUpdater.quitAndInstall(false, true);
    }
  }

  private update(
    state: DesktopUpdateStatus["state"],
    message: string,
    extra: Partial<DesktopUpdateStatus> = {},
  ): void {
    this.current = {
      ...this.current,
      ...extra,
      state,
      message,
      checked_at: new Date().toISOString(),
    };
    for (const listener of this.listeners) listener(this.current);
  }
}
