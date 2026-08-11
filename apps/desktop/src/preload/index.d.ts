import type { DesktopBridge } from "@job-apply-pro/contracts";

declare global {
  interface Window {
    jobApplyPro: DesktopBridge;
  }
}

export {};
