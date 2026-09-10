export type SecurityHeader = { key: string; value: string };

type SecurityHeaderOptions = {
  environment: string;
  apiBaseUrl: string;
  enableHsts: boolean;
};

function apiOrigin(apiBaseUrl: string): string {
  const parsed = new URL(apiBaseUrl);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must use HTTP or HTTPS.");
  }
  return parsed.origin;
}

export function buildContentSecurityPolicy(
  environment: string,
  apiBaseUrl: string,
): string {
  const development = environment !== "production";
  const scriptSources = ["'self'", "'unsafe-inline'"];
  const connectSources = ["'self'", apiOrigin(apiBaseUrl)];
  if (development) {
    scriptSources.push("'unsafe-eval'");
    connectSources.push("ws:", "wss:");
  }

  return [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "frame-src 'none'",
    "form-action 'self'",
    `script-src ${scriptSources.join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self' data:",
    `connect-src ${connectSources.join(" ")}`,
    "worker-src 'self' blob:",
    "media-src 'none'",
  ].join("; ");
}

export function buildSecurityHeaders(
  options: SecurityHeaderOptions,
): SecurityHeader[] {
  const headers: SecurityHeader[] = [
    {
      key: "Content-Security-Policy",
      value: buildContentSecurityPolicy(
        options.environment,
        options.apiBaseUrl,
      ),
    },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    },
    { key: "X-Frame-Options", value: "DENY" },
  ];
  if (options.environment === "production" && options.enableHsts) {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000; includeSubDomains",
    });
  }
  return headers;
}

export function mockTranscriptionEnabled(
  environment: string | undefined,
  configuredValue: string | undefined,
): boolean {
  return environment === "development" && configuredValue === "true";
}
