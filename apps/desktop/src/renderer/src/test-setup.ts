import "@testing-library/jest-dom/vitest";

import type { DesktopBridge } from "@job-apply-pro/contracts";

const bridge: DesktopBridge = {
  platform: "win32",
  versions: { electron: "test", chrome: "test", node: "test" },
  workbench: {
    getStatus: async () => ({
      state: "ready",
      message: "Encrypted local backend connected.",
      checked_at: new Date(0).toISOString(),
    }),
    listWorkflows: async () => [],
    listBrowserSessions: async () => [],
    getCandidateKnowledge: async (profileId) => ({
      profile_id: profileId,
      documents: [],
      claims: [],
      answers: [],
    }),
    selectAndImportResume: async () => null,
    reviewCandidateClaim: async () => {
      throw new Error("Not implemented in this test.");
    },
    createCandidate: async () => {
      throw new Error("Not implemented in this test.");
    },
    startMockWorkflow: async () => {
      throw new Error("Not implemented in this test.");
    },
    controlWorkflow: async () => {
      throw new Error("Not implemented in this test.");
    },
    onStatus: () => () => undefined,
  },
};

Object.defineProperty(window, "jobApplyPro", {
  value: bridge,
  configurable: true,
});
