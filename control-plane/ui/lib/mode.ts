// Mock mode serves fixture data with a fake session. It is the default when no API is configured.
export function isMock(): boolean {
  return process.env.UI_MOCK === "1" || !process.env.PLATFORM_API_URL;
}
