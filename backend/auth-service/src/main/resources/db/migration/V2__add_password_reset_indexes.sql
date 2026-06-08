-- ============================================================================
-- Password Reset Security & Performance Indexes
-- ============================================================================
-- Purpose: Add critical indexes for password reset functionality
-- Performance Impact: Improves query performance from O(n) to O(log n)
-- Security Impact: Enables efficient rate limiting and prevents table scans
-- ============================================================================

-- OTP Event Log Indexes
-- Critical for OTP verification and rate limiting queries
CREATE INDEX IF NOT EXISTS idx_otp_user_type_verified_expiry
ON otp_event_log(auth_user_id, otp_type, verified, expires_at);

-- Used for failed attempt tracking and rate limiting
CREATE INDEX IF NOT EXISTS idx_otp_user_type_created
ON otp_event_log(auth_user_id, otp_type, created_at DESC);

-- Password Reset Token Indexes
-- Used for rate limiting password reset requests
CREATE INDEX IF NOT EXISTS idx_password_reset_user_expiry
ON password_reset_tokens(auth_user_id, expiry_date);

-- Used for cleanup of expired tokens
CREATE INDEX IF NOT EXISTS idx_password_reset_expiry
ON password_reset_tokens(expiry_date);

-- Email Event Log Indexes
-- Critical for email rate limiting
CREATE INDEX IF NOT EXISTS idx_email_recipient_created
ON email_event_log(recipient, created_at DESC);

-- Used for cleanup of old email logs
CREATE INDEX IF NOT EXISTS idx_email_created
ON email_event_log(created_at DESC);

-- OTP Event Log cleanup index
CREATE INDEX IF NOT EXISTS idx_otp_expires_at
ON otp_event_log(expires_at);

-- ============================================================================
-- Index Verification Queries (for testing)
-- ============================================================================
-- Run after migration to verify indexes exist:
--
-- PostgreSQL:
-- SELECT indexname, tablename FROM pg_indexes
-- WHERE tablename IN ('otp_event_log', 'password_reset_tokens', 'email_event_log');
--
-- MySQL:
-- SHOW INDEX FROM otp_event_log;
-- SHOW INDEX FROM password_reset_tokens;
-- SHOW INDEX FROM email_event_log;
-- ============================================================================
