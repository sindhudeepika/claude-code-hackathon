'use strict';

module.exports = {
  port: parseInt(process.env.PORT || '3000', 10),
  nodeEnv: process.env.NODE_ENV || 'development',

  db: {
    host: process.env.DB_HOST || 'localhost',
    port: parseInt(process.env.DB_PORT || '5432', 10),
    database: process.env.DB_NAME || 'contoso',
    user: process.env.DB_USER || 'contoso',
    password: process.env.DB_PASSWORD || 'dev-only-not-for-prod',
    ssl: process.env.DB_SSL === 'false' ? false : { rejectUnauthorized: true },
    max: parseInt(process.env.DB_POOL_MAX || '10', 10),
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 5000,
  },

  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
    password: process.env.REDIS_PASSWORD || undefined,
    tls: process.env.REDIS_TLS === 'true',
  },

  // LEGACY: on-prem auth service. In Azure this MUST be set via AUTH_SERVICE_URL env var.
  // Default IP (10.0.1.45) is not routable in Azure — see discovery finding #1.
  // Phase 2: replace with Azure AD B2C OIDC validation.
  authServiceUrl: process.env.AUTH_SERVICE_URL || 'http://10.0.1.45:8080/auth/validate',

  // LEGACY: on-prem wrote logs to a local file. Set LOG_FILE=null (or omit) for cloud-safe
  // stdout logging. Do NOT set this in Azure Container Apps — see discovery finding #2.
  logFile: process.env.LOG_FILE || null,

  sessionTtlSeconds: parseInt(process.env.SESSION_TTL_SECONDS || '3600', 10),

  // PII fields — never log these raw
  piiFields: ['email', 'phone', 'account_number', 'sort_code'],
};
