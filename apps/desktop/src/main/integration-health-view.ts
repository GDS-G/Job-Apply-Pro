import type { IntegrationHealth } from "@job-apply-pro/contracts";

/** Remove the main-process credential handle before integration health crosses IPC. */
export function integrationHealthForRenderer(
  values: IntegrationHealth[],
): IntegrationHealth[] {
  return values.map(
    ({ credential_reference: _credentialReference, ...value }) =>
      structuredClone(value),
  );
}
