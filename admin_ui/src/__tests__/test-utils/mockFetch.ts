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

/**
 * Mocks one SSE stream connection (`GET /realtime-quotes/stream`) — queues a
 * `Response` whose `body` is a `ReadableStream` emitting the given events as
 * `data: {...}\n\n` frames. The stream is deliberately left open (never
 * closed) to mirror a real SSE connection.
 */
export function mockFetchStreamOnce(events: Array<Record<string, unknown>>) {
  const encoder = new TextEncoder();
  let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller;
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      }
    },
  });
  const spy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: true,
    status: 200,
    headers: new Headers({ "content-type": "text/event-stream" }),
    body: stream,
  } as unknown as Response);
  return {
    spy,
    /** Push an additional event onto the still-open stream. */
    push(event: Record<string, unknown>) {
      controllerRef?.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
    },
    close() {
      controllerRef?.close();
    },
  };
}

/** Queues a rejected `fetch` — simulates the SSE stream failing to connect. */
export function mockFetchStreamError() {
  return vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("stream error"));
}

/** Queues a `401` response for the SSE stream endpoint — simulates the
 * session token expiring mid-connection (distinct from a transport drop). */
export function mockFetchStreamUnauthorized() {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: false,
    status: 401,
    statusText: "Unauthorized",
    body: null,
    json: async () => ({ detail: "Unauthorized" }),
  } as unknown as Response);
}
