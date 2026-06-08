-- ============================================================================
-- Authentication & Security Indexes
-- ============================================================================
-- Purpose: Add critical indexes for authentication, authorization, and security
-- Performance Impact: Improves query performance for login, token validation, and security events
-- Security Impact: Enables efficient rate limiting, token revocation checks, and audit logging
-- ============================================================================

-- Token Store Indexes
-- CRITICAL: Fast token lookup for authentication (jwt filter checks this on every request)
CREATE INDEX IF NOT EXISTS idx_token_store_token_string
ON token_store(token_string);

-- CRITICAL: Fast lookup of user's tokens and revocation status
CREATE INDEX IF NOT EXISTS idx_token_store_user_revoked
ON token_store(user_id, revoked);

-- Used for cleanup of expired tokens and checking token validity
CREATE INDEX IF NOT EXISTS idx_token_store_expiry
ON token_store(expires_at);

-- Combined index for common query pattern (user's active tokens)
CREATE INDEX IF NOT EXISTS idx_token_store_user_type_expiry
ON token_store(user_id, token_type, expires_at DESC);

-- Auth User Credentials Indexes
-- CRITICAL: Fast user lookup during login (by email)
CREATE INDEX IF NOT EXISTS idx_auth_user_email
ON auth_user_credentials(email);

-- Used for account status checks (active/locked/disabled users)
CREATE INDEX IF NOT EXISTS idx_auth_user_status
ON auth_user_credentials(status);

-- Combined index for login queries (email + status check)
CREATE INDEX IF NOT EXISTS idx_auth_user_email_status
ON auth_user_credentials(email, status);

-- Security Events Indexes
-- CRITICAL: Fast security event lookups for audit trails and incident response
CREATE INDEX IF NOT EXISTS idx_security_events_user_type_time
ON security_events(auth_user_id, event_type, event_time DESC);

-- Used for security monitoring and incident detection
CREATE INDEX IF NOT EXISTS idx_security_events_type_time
ON security_events(event_type, event_time DESC);

-- Used for IP-based security analysis
CREATE INDEX IF NOT EXISTS idx_security_events_ip_time
ON security_events(ip_address, event_time DESC);

-- OAuth Identity Indexes
-- Fast lookup of OAuth-linked accounts
CREATE INDEX IF NOT EXISTS idx_oauth_identity_user
ON oauth_identity(auth_user_id);

-- Fast lookup by OAuth provider and provider user ID
CREATE INDEX IF NOT EXISTS idx_oauth_identity_provider
ON oauth_identity(provider, provider_user_id);

-- SMS Event Log Indexes
-- CRITICAL: Fast rate limiting checks for SMS sending
CREATE INDEX IF NOT EXISTS idx_sms_recipient_created
ON sms_event_log(recipient, created_at DESC);

-- Used for SMS delivery tracking and debugging
CREATE INDEX IF NOT EXISTS idx_sms_message_sid
ON sms_event_log(message_sid);

-- Used for user's SMS history and rate limiting
CREATE INDEX IF NOT EXISTS idx_sms_user_created
ON sms_event_log(auth_user_id, created_at DESC);

-- Used for OTP-specific rate limiting
CREATE INDEX IF NOT EXISTS idx_sms_user_otp_created
ON sms_event_log(auth_user_id, is_otp, created_at DESC);

-- ============================================================================
-- Performance Notes
-- ============================================================================
-- These indexes support the following critical operations:
--
-- 1. JWT Authentication Filter (EVERY REQUEST):
--    - token_string lookup: idx_token_store_token_string
--    - revocation check: idx_token_store_user_revoked
--
-- 2. Login Endpoint:
--    - email lookup: idx_auth_user_email_status
--    - account status check: idx_auth_user_status
--
-- 3. Rate Limiting:
--    - SMS rate limits: idx_sms_recipient_created, idx_sms_user_otp_created
--    - Email rate limits: already covered in V2 migration
--
-- 4. Security Monitoring:
--    - Audit logs: idx_security_events_user_type_time
--    - Failed login tracking: idx_security_events_type_time
--    - IP-based analysis: idx_security_events_ip_time
--
-- 5. OAuth Integration:
--    - OAuth user lookup: idx_oauth_identity_user
--    - Provider account linking: idx_oauth_identity_provider
--
-- ============================================================================

-- ============================================================================
-- Index Verification Queries
-- ============================================================================
-- Run after migration to verify indexes exist:
--
-- PostgreSQL:
-- SELECT schemaname, tablename, indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename IN ('token_store', 'auth_user_credentials', 'security_events',
--                     'oauth_identity', 'sms_event_log')
-- ORDER BY tablename, indexname;
--
-- MySQL:
-- SHOW INDEX FROM token_store;
-- SHOW INDEX FROM auth_user_credentials;
-- SHOW INDEX FROM security_events;
-- SHOW INDEX FROM oauth_identity;
-- SHOW INDEX FROM sms_event_log;
-- ============================================================================
