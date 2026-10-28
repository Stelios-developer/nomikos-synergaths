import "dotenv/config";

import { betterAuth } from "better-auth";
import { Pool } from "pg";
import { isProduction } from "./runtime.js";

const databaseUrl = process.env.DATABASE_URL;
const secret = process.env.BETTER_AUTH_SECRET;

if (!databaseUrl) {
  throw new Error("DATABASE_URL is required for Better Auth.");
}

if (!secret || secret.length < 32) {
  throw new Error("BETTER_AUTH_SECRET must be set and contain at least 32 characters.");
}

const appOrigin = process.env.APP_ORIGIN ?? "http://localhost:5173";
const trustedOrigins = [
  appOrigin,
  ...(process.env.TRUSTED_ORIGINS ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean),
];

const cookieDomain = process.env.COOKIE_DOMAIN?.trim() || undefined;
const requireEmailVerification = process.env.REQUIRE_EMAIL_VERIFICATION === "true";

if (isProduction) {
  if (!requireEmailVerification) {
    throw new Error("REQUIRE_EMAIL_VERIFICATION=true is mandatory in production.");
  }
  if (!process.env.RESEND_API_KEY || !process.env.EMAIL_FROM) {
    throw new Error("Production email verification requires RESEND_API_KEY and EMAIL_FROM.");
  }
  if (!process.env.BETTER_AUTH_URL?.startsWith("https://") || !appOrigin.startsWith("https://")) {
    throw new Error("BETTER_AUTH_URL and APP_ORIGIN must use HTTPS in production.");
  }
}

export const pool = new Pool({ connectionString: databaseUrl });

async function sendEmail({ to, subject, html }: { to: string; subject: string; html: string }) {
  const apiKey = process.env.RESEND_API_KEY;
  // Update an old sender display name without touching its verified email address.
  const from = process.env.EMAIL_FROM?.replace(/^\s*NEXUS\s*(?=<)/i, "Documents Made Clear ");

  if (!apiKey || !from) {
    if (isProduction) {
      throw new Error("RESEND_API_KEY and EMAIL_FROM are required in production for account emails.");
    }
    // Development has no external email account by default. Do not log tokens
    // or password-reset URLs, because terminal history is not a safe mailbox.
    throw new Error("Email delivery is not configured. Set RESEND_API_KEY and EMAIL_FROM.");
  }

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ from, to: [to], subject, html }),
  });

  if (!response.ok) {
    throw new Error("Could not deliver the account email.");
  }
}

export const auth = betterAuth({
  appName: "Documents Made Clear",
  database: pool,
  secret,
  baseURL: process.env.BETTER_AUTH_URL ?? "http://localhost:3001",
  basePath: "/api/auth",
  trustedOrigins,
  emailAndPassword: {
    enabled: true,
    requireEmailVerification,
    minPasswordLength: 12,
    maxPasswordLength: 128,
    sendResetPassword: async ({ user, url }) => {
      await sendEmail({
        to: user.email,
        subject: "Reset your Documents Made Clear password",
        html: `<p><strong>Documents Made Clear</strong></p><p>Use this secure link to reset your password:</p><p><a href="${url}">Reset password</a></p>`,
      });
    },
  },
  emailVerification: {
    sendOnSignUp: requireEmailVerification,
    sendVerificationEmail: async ({ user, url }) => {
      await sendEmail({
        to: user.email,
        subject: "Verify your Documents Made Clear email",
        html: `<p><strong>Documents Made Clear</strong></p><p>Verify your email to activate your private document workspace:</p><p><a href="${url}">Verify email</a></p>`,
      });
    },
  },
  advanced: {
    cookiePrefix: "nexus",
    ...(cookieDomain ? { crossSubDomainCookies: { enabled: true, domain: cookieDomain } } : {}),
    defaultCookieAttributes: {
      httpOnly: true,
      secure: isProduction,
      sameSite: "lax",
    },
  },
  // Database-backed limits apply consistently across multiple auth-service
  // instances; login and reset routes receive deliberately tighter limits.
  rateLimit: {
    enabled: true,
    window: 60,
    max: 60,
    storage: "database",
    customRules: {
      "/sign-in/email": { window: 900, max: 5 },
      "/sign-up/email": { window: 3600, max: 5 },
      "/request-password-reset": { window: 3600, max: 3 },
    },
  },
});
