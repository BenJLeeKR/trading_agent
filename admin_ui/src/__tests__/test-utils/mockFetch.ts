import { vi } from "vitest";

export function mockFetchOnce(data: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => data,
  } as Response);
}

export function mockFetchError(status: number, detail: string) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: false,
    status,
    statusText: detail,
    json: async () => ({ detail }),
  } as Response);
}

export function mockFetchNetworkError() {
  return vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
    new Error("Network error"),
  );
}
