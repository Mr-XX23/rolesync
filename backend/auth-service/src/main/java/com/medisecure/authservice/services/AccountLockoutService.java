package com.medisecure.authservice.services;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.concurrent.TimeUnit;

/**
 * Service for managing account lockout after failed login attempts.
 * Uses in-memory cache to track attempts across distributed systems.
 * Security: Prevents brute force attacks by temporarily locking accounts.
 */
@Service
@Slf4j
public class AccountLockoutService {

    private static final int MAX_FAILED_ATTEMPTS = 5;
    private static final int LOCKOUT_DURATION_MINUTES = 15;

    // Cache: key = username, value = FailedAttemptInfo
    private final Cache<String, FailedAttemptInfo> failedAttemptsCache;

    public AccountLockoutService() {
        this.failedAttemptsCache = Caffeine.newBuilder()
                .expireAfterWrite(LOCKOUT_DURATION_MINUTES, TimeUnit.MINUTES)
                .maximumSize(10000)
                .build();
    }

    /**
     * Record a failed login attempt for a username.
     * Automatically locks account if max attempts reached.
     */
    public void recordFailedAttempt(String username) {
        FailedAttemptInfo info = failedAttemptsCache.get(username, k -> new FailedAttemptInfo());

        if (info != null) {
            info.incrementAttempts();

            if (info.getAttempts() >= MAX_FAILED_ATTEMPTS) {
                info.setLockedUntil(LocalDateTime.now().plusMinutes(LOCKOUT_DURATION_MINUTES));
                log.warn("Account locked due to {} failed attempts: {}", MAX_FAILED_ATTEMPTS, username);
            }

            failedAttemptsCache.put(username, info);
            log.debug("Failed attempt {} for user: {}", info.getAttempts(), username);
        }
    }

    /**
     * Check if account is currently locked.
     * 
     * @return true if locked, false if allowed to login
     */
    public boolean isAccountLocked(String username) {
        FailedAttemptInfo info = failedAttemptsCache.getIfPresent(username);

        if (info == null) {
            return false;
        }

        // Check if lockout period has expired
        if (info.getLockedUntil() != null && LocalDateTime.now().isAfter(info.getLockedUntil())) {
            // Lockout expired, clear the record
            failedAttemptsCache.invalidate(username);
            log.info("Lockout period expired for user: {}", username);
            return false;
        }

        return info.getLockedUntil() != null;
    }

    /**
     * Get minutes remaining until account is unlocked.
     * 
     * @return minutes until unlock, or 0 if not locked
     */
    public long getMinutesUntilUnlock(String username) {
        FailedAttemptInfo info = failedAttemptsCache.getIfPresent(username);

        if (info == null || info.getLockedUntil() == null) {
            return 0;
        }

        LocalDateTime now = LocalDateTime.now();
        if (now.isAfter(info.getLockedUntil())) {
            return 0;
        }

        return ChronoUnit.MINUTES.between(now, info.getLockedUntil());
    }

    /**
     * Reset failed attempts after successful login.
     */
    public void resetFailedAttempts(String username) {
        failedAttemptsCache.invalidate(username);
        log.debug("Reset failed attempts for user: {}", username);
    }

    /**
     * Get current number of failed attempts.
     */
    public int getFailedAttempts(String username) {
        FailedAttemptInfo info = failedAttemptsCache.getIfPresent(username);
        return info != null ? info.getAttempts() : 0;
    }

    /**
     * Data class to track failed login attempts.
     */
    private static class FailedAttemptInfo {
        private int attempts = 0;
        private LocalDateTime lockedUntil;

        public void incrementAttempts() {
            this.attempts++;
        }

        public int getAttempts() {
            return attempts;
        }

        public LocalDateTime getLockedUntil() {
            return lockedUntil;
        }

        public void setLockedUntil(LocalDateTime lockedUntil) {
            this.lockedUntil = lockedUntil;
        }
    }
}
