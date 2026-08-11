import { contextBridge } from "electron";

const apiBaseUrl =
  process.env.JAP_API_BASE_URL ?? "http://127.0.0.1:8765/api/v1";

contextBridge.exposeInMainWorld("jobApplyPro", {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
  apiBaseUrl,
});
