// Client-side beacon for the storefront analytics project.
export const ANALYTICS_KEY = "fake-test-key-0000";

export function track(event: string): void {
  void fetch("/api/analytics", {
    method: "POST",
    headers: { "content-type": "application/json", "x-analytics-key": ANALYTICS_KEY },
    body: JSON.stringify({ event }),
  });
}
