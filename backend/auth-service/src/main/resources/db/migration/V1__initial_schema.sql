-- ============================================================================
-- Initial Database Schema for Authentication Service
-- ============================================================================
-- Purpose: Create all base tables for authentication, authorization, and user management
-- Version: 1.0
-- Date: 2026-02-16
-- ============================================================================

-- ============================================================================
-- Core Authentication Tables
-- ============================================================================

-- Auth User Credentials Table
-- Stores core authentication credentials for all users
CREATE TABLE IF NOT EXISTS auth_user_credentials (
    auth_user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(64) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone_number VARCHAR(20) UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    
    -- Account status management
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    -- Status values: ACTIVE, PENDING, LOCKED, DISABLED, DELETED
    
    -- Verification flags
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    phone_verified BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Account type and permissions
    role VARCHAR(32) NOT NULL DEFAULT 'USER',
    -- Role values: USER, ADMIN, DOCTOR, PATIENT, STAFF
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    
    -- Failed login tracking for security
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMP,
    
    CONSTRAINT chk_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT chk_status CHECK (status IN ('ACTIVE', 'PENDING', 'LOCKED', 'DISABLED', 'DELETED')),
    CONSTRAINT chk_role CHECK (role IN ('USER', 'ADMIN', 'DOCTOR', 'PATIENT', 'STAFF'))
);

-- Token Store Table
-- Stores JWT tokens for revocation tracking and session management
CREATE TABLE IF NOT EXISTS token_store (
    token_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID NOT NULL REFERENCES auth_user_credentials(auth_user_id) ON DELETE CASCADE,
    token_string TEXT NOT NULL,
    token_type VARCHAR(16) NOT NULL DEFAULT 'ACCESS',
    -- Token types: ACCESS, REFRESH
    
    issued_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    
    device_fingerprint VARCHAR(128),
    
    CONSTRAINT chk_token_type CHECK (token_type IN ('ACCESS', 'REFRESH'))
);

-- ============================================================================
-- Password Reset & Recovery Tables
-- ============================================================================

-- Password Reset Tokens
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID NOT NULL REFERENCES auth_user_credentials(auth_user_id) ON DELETE CASCADE,
    token_hash VARCHAR(255) UNIQUE NOT NULL,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expiry_date TIMESTAMP NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    
    ip_address VARCHAR(45),
    user_agent TEXT
);

-- OTP Event Log
-- Tracks all OTP generation and verification for security and rate limiting
CREATE TABLE IF NOT EXISTS otp_event_log (
    otp_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID NOT NULL REFERENCES auth_user_credentials(auth_user_id) ON DELETE CASCADE,
    
    otp_code VARCHAR(128) NOT NULL,
    sent_to VARCHAR(100) NOT NULL,
    otp_type VARCHAR(32) NOT NULL,
    -- OTP types: EMAIL_VERIFICATION, PHONE_VERIFICATION, PASSWORD_RESET, MFA
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at TIMESTAMP,
    
    CONSTRAINT chk_otp_type CHECK (otp_type IN ('EMAIL_VERIFICATION', 'PHONE_VERIFICATION', 'PASSWORD_RESET', 'MFA', 'REGISTRATION'))
);

-- ============================================================================
-- Communication Tracking Tables
-- ============================================================================

-- Email Event Log
-- Tracks all emails sent for auditing and debugging
CREATE TABLE IF NOT EXISTS email_event_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID REFERENCES auth_user_credentials(auth_user_id) ON DELETE SET NULL,
    
    recipient VARCHAR(255) NOT NULL,
    subject VARCHAR(500) NOT NULL,
    email_type VARCHAR(32) NOT NULL,
    -- Email types: VERIFICATION, PASSWORD_RESET, WELCOME, NOTIFICATION, ALERT
    
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    -- Status values: PENDING, SENT, FAILED, BOUNCED, DELIVERED
    
    message_id VARCHAR(100),
    error_message TEXT,
    
    retry_attempts INT NOT NULL DEFAULT 0,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    delivered_at TIMESTAMP,
    
    CONSTRAINT chk_email_type CHECK (email_type IN ('VERIFICATION', 'PASSWORD_RESET', 'WELCOME', 'NOTIFICATION', 'ALERT')),
    CONSTRAINT chk_email_status CHECK (status IN ('PENDING', 'SENT', 'FAILED', 'BOUNCED', 'DELIVERED'))
);

-- SMS Event Log
-- Tracks all SMS sent for auditing, debugging, and cost tracking
CREATE TABLE IF NOT EXISTS sms_event_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID REFERENCES auth_user_credentials(auth_user_id) ON DELETE SET NULL,
    
    recipient VARCHAR(20) NOT NULL,
    from_number VARCHAR(20) NOT NULL,
    message_content VARCHAR(500) NOT NULL,
    
    sms_type VARCHAR(32) NOT NULL,
    -- SMS types: OTP_VERIFICATION, PASSWORD_RESET, NOTIFICATION, ALERT, MFA_CODE
    
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    -- Status values: PENDING, QUEUED, SENT, DELIVERED, FAILED, UNDELIVERED
    
    message_sid VARCHAR(50),
    error_message TEXT,
    error_code VARCHAR(10),
    
    retry_attempts INT NOT NULL DEFAULT 0,
    cost DECIMAL(10, 4),
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    delivered_at TIMESTAMP,
    
    is_otp BOOLEAN NOT NULL DEFAULT FALSE,
    country_code VARCHAR(5),
    
    CONSTRAINT chk_sms_type CHECK (sms_type IN ('OTP_VERIFICATION', 'PASSWORD_RESET', 'NOTIFICATION', 'ALERT', 'MFA_CODE')),
    CONSTRAINT chk_sms_status CHECK (status IN ('PENDING', 'QUEUED', 'SENT', 'DELIVERED', 'FAILED', 'UNDELIVERED'))
);

-- ============================================================================
-- Security & Audit Tables
-- ============================================================================

-- Security Events
-- Tracks authentication events, security incidents, and suspicious activity
CREATE TABLE IF NOT EXISTS security_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID REFERENCES auth_user_credentials(auth_user_id) ON DELETE SET NULL,
    
    event_type VARCHAR(50) NOT NULL,
    -- Event types: LOGIN_SUCCESS, LOGIN_FAILED, LOGOUT, PASSWORD_CHANGE, 
    --              ACCOUNT_LOCKED, SUSPICIOUS_ACTIVITY, TOKEN_REVOKED, etc.
    
    event_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    
    details JSONB,
    severity VARCHAR(20) DEFAULT 'INFO',
    -- Severity: INFO, WARNING, ERROR, CRITICAL
    
    CONSTRAINT chk_severity CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL'))
);

-- OAuth Identity Mapping
-- Maps OAuth provider accounts to local user accounts
CREATE TABLE IF NOT EXISTS oauth_identity (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID NOT NULL REFERENCES auth_user_credentials(auth_user_id) ON DELETE CASCADE,
    
    provider VARCHAR(32) NOT NULL,
    -- Providers: GOOGLE, FACEBOOK, GITHUB, etc.
    
    provider_user_id VARCHAR(255) NOT NULL,
    provider_email VARCHAR(255),
    
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMP,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    
    UNIQUE(provider, provider_user_id),
    CONSTRAINT chk_provider CHECK (provider IN ('GOOGLE', 'FACEBOOK', 'GITHUB', 'MICROSOFT'))
);

-- ============================================================================
-- Triggers for Automatic Timestamp Updates
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_auth_user_updated_at
    BEFORE UPDATE ON auth_user_credentials
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Initial Data
-- ============================================================================

-- Create default admin user (password: Admin@123 - MUST BE CHANGED IN PRODUCTION!)
-- Password hash for 'Admin@123' using BCrypt with strength 12
INSERT INTO auth_user_credentials (
    username, email, password_hash, status, role, email_verified
) VALUES (
    'admin',
    'admin@medisecure.com',
    '$2a$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY0lZhNGU5r.Gza',
    'ACTIVE',
    'ADMIN',
    TRUE
) ON CONFLICT (email) DO NOTHING;

-- ============================================================================
-- Comments for Documentation
-- ============================================================================

COMMENT ON TABLE auth_user_credentials IS 'Core user authentication and profile data';
COMMENT ON TABLE token_store IS 'JWT token storage for revocation tracking';
COMMENT ON TABLE password_reset_tokens IS 'Password reset request tracking';
COMMENT ON TABLE otp_event_log IS 'OTP generation and verification audit trail';
COMMENT ON TABLE email_event_log IS 'Email delivery tracking and debugging';
COMMENT ON TABLE sms_event_log IS 'SMS delivery tracking, cost analysis, and rate limiting';
COMMENT ON TABLE security_events IS 'Security audit log for authentication events';
COMMENT ON TABLE oauth_identity IS 'OAuth provider account mapping';

COMMENT ON COLUMN auth_user_credentials.status IS 'Account status: ACTIVE, PENDING, LOCKED, DISABLED, DELETED';
COMMENT ON COLUMN auth_user_credentials.role IS 'User role: USER, ADMIN, DOCTOR, PATIENT, STAFF';
COMMENT ON COLUMN token_store.revoked IS 'True if token has been manually revoked (logout)';
COMMENT ON COLUMN sms_event_log.is_otp IS 'True if SMS contains OTP code (for special rate limiting)';

-- ============================================================================
-- Schema Version Info
-- ============================================================================

-- This is V1 - initial schema creation
-- Next migrations: V2 (indexes), V3 (additional indexes), V4+ (schema modifications)
