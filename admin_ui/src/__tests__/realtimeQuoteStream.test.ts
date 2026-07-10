/**
 * `subscribeRealtimeQuoteStream()` (Phase 4 push relay) — 401 인증 만료 처리.
 *
 * 이 스트림 함수는 공통 `request()` 래퍼를 거치지 않고 직접 `fetch()`를 호출하기
 * 때문에, `/realtime-quotes/stream`이 401을 반환해도 기존 REST API처럼 자동으로
 * `clearStoredToken()`/`_onUnauthorized()`가 실행되지 않고 단순 transport error로
 * 취급돼 backoff 재시도만 반복될 수 있었다. 이 파일은 401이 "로그인 세션 종료"
 * 이벤트로 처리되고, 재시도 루프가 완전히 멈추는지를 검증한다.
 */
import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import {
  subscribeRealtimeQuoteStream,
  setStoredToken,
  getStoredToken,
  setOnUnauthorized,
} from "../api/client";
import { VALID_TOKEN } from "./test-utils/fixtures";
import { mockFetchStreamOnce, mockFetchStreamUnauthorized } from "./test-utils/mockFetch";

beforeEach(() => {
  setStoredToken(VALID_TOKEN);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  setOnUnauthorized(null as unknown as () => void);
});

describe("subscribeRealtimeQuoteStream 401 handling", () => {
  it("clears the token, calls the unauthorized callback, and stops retrying", async () => {
    mockFetchStreamUnauthorized();
    const onUnauthorized = vi.fn();
    setOnUnauthorized(onUnauthorized);
    const onTransportError = vi.fn();

    const unsubscribe = subscribeRealtimeQuoteStream("005930", {
      onEvent: () => {},
      onTransportError,
    });

    // Let the in-flight runOnce()/401 handling settle.
    await vi.waitFor(() => {
      expect(onUnauthorized).toHaveBeenCalledTimes(1);
    });
    expect(getStoredToken()).toBeNull();
    // 401 is NOT a transport error — it must not trigger the degraded-fallback path.
    expect(onTransportError).not.toHaveBeenCalled();

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const callsAfterUnauthorized = fetchSpy.mock.calls.length;

    // Advance well past the max backoff window — if the retry loop were still
    // alive it would have refired the stream fetch by now.
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchSpy.mock.calls.length).toBe(callsAfterUnauthorized);

    unsubscribe();
  });

  it("still retries with backoff on an ordinary transport error (unaffected by the 401 fix)", async () => {
    // First attempt: plain connection failure (not 401) — must still go
    // through the existing onTransportError/backoff path, then succeed.
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("network blip"));
    const stream = mockFetchStreamOnce([]);
    const onTransportError = vi.fn();
    const onEvent = vi.fn();

    const unsubscribe = subscribeRealtimeQuoteStream("005930", {
      onEvent,
      onTransportError,
    });

    await vi.waitFor(() => {
      expect(onTransportError).toHaveBeenCalledTimes(1);
    });

    await vi.advanceTimersByTimeAsync(1_500);
    await vi.waitFor(() => {
      expect(stream.spy).toHaveBeenCalled();
    });

    unsubscribe();
  });
});
