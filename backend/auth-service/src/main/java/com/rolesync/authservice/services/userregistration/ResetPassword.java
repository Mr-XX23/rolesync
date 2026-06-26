package com.rolesync.authservice.services.userregistration;

import com.rolesync.authservice.dto.userregistrations.RegistrationResponse;
import com.rolesync.authservice.exceptions.BadRequestException;
import com.rolesync.authservice.models.AuthUserCredentials;
import com.rolesync.authservice.models.OtpEventLog;
import com.rolesync.authservice.models.PasswordResetToken;
import com.rolesync.authservice.repository.OtpEventLogRepository;
import com.rolesync.authservice.repository.PasswordResetTokenRepository;
import com.rolesync.authservice.repository.UserRepository;
import com.rolesync.authservice.services.AuthSecurityEventService;
import com.rolesync.authservice.services.EmailService;
import com.rolesync.authservice.services.OtpService;
import com.rolesync.authservice.services.SmsService;
import jakarta.persistence.EntityManager;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.UUID;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
@Slf4j
public class ResetPassword {

    private final AuthSecurityEventService securityEventService;
    private final UserRepository userRepository;
    private final OtpService otpService;
    private final EmailService emailService;
    private final SmsService smsService;
    private final PasswordEncoder passwordEncoder;
    private final PasswordResetTokenRepository passwordResetTokenRepository;
    private final EntityManager entityManager;
    private final OtpEventLogRepository otpEventLogRepository;

    private static final Pattern EMAIL_PATTERN = Pattern.compile(
            "^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$");

    private static final Pattern PHONE_PATTERN = Pattern.compile("^\\+?[1-9]\\d{1,14}$");

    private static final Pattern PASSWORD_PATTERN = Pattern.compile(
            "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[@$!%*?&])[A-Za-z\\d@$!%*?&]{8,}$");

    private static final int MAX_VERIFICATION_ATTEMPTS = 5; // Max failed verification attempts before lockout
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    /**
     * Generate cryptographically secure reset token (256-bit).
     * Uses SecureRandom for maximum entropy.
     */
    private String generateSecureResetToken() {
        byte[] randomBytes = new byte[32]; // 256 bits
        SECURE_RANDOM.nextBytes(randomBytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(randomBytes);
    }

    /**
     * Initiate password reset for user using email or phone.
     */
    @Transactional(isolation = Isolation.SERIALIZABLE)
    public RegistrationResponse resetPassword(String userContact, HttpServletRequest httpRequest) {

        securityEventService.logSecurityEvent(
                null,
                "PASSWORD_RESET_ATTEMPT",
                "Password reset initiated for: " + maskContact(userContact),
                httpRequest);

        // Validate contact format
        ContactType contactType = determineContactType(userContact);
        if (contactType == null) {
            securityEventService.logSecurityEvent(
                    null,
                    "PASSWORD_RESET_FAILED",
                    "Invalid contact format provided",
                    httpRequest);
            throw new BadRequestException("Invalid email or phone number format");
        }

        // Find user
        AuthUserCredentials user = userRepository.findByEmailOrPhoneNumber(userContact, userContact)
                .orElseThrow(() -> {
                    log.warn("Password reset attempted for non-existent user: {}", maskContact(userContact));
                    securityEventService.logSecurityEvent(
                            null,
                            "PASSWORD_RESET_FAILED",
                            "Password reset attempted for non-existent user",
                            httpRequest);
                    return new BadRequestException("If this account exists, you will receive a reset code");
                });

        // Check user status
        if (user.getStatus() == AuthUserCredentials.Status.SUSPENDED ||
                user.getStatus() == AuthUserCredentials.Status.LOCKED) {
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_FAILED",
                    "Password reset attempted for suspended/locked account",
                    httpRequest);
            throw new BadRequestException("Account is suspended or locked");
        }

        // Check rate limiting
        if (isPasswordResetRateLimited(user.getAuthUserId())) {
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_RATE_LIMITED",
                    "Too many password reset attempts",
                    httpRequest);
            throw new BadRequestException("Too many password reset attempts. Please try again later.");
        }

        // Invalidate any existing tokens
        invalidateExistingTokens(user.getAuthUserId());

        if (contactType == ContactType.EMAIL) {
            return handleEmailReset(user, httpRequest);
        } else {
            return handlePhoneReset(user, httpRequest);
        }
    }

    /**
     * Confirm password reset using token and new password.
     */
    @Transactional(isolation = Isolation.SERIALIZABLE)
    public RegistrationResponse confirmPasswordReset(
            String token,
            String newPassword,
            HttpServletRequest httpRequest) {

        securityEventService.logSecurityEvent(
                null,
                "PASSWORD_RESET_CONFIRM_ATTEMPT",
                "Password reset confirmation attempted",
                httpRequest);

        // Validate password strength
        if (!isValidPassword(newPassword)) {
            securityEventService.logSecurityEvent(
                    null,
                    "PASSWORD_RESET_CONFIRM_FAILED",
                    "Weak password provided",
                    httpRequest);
            throw new BadRequestException(
                    "Password must be at least 8 characters with uppercase, lowercase, number, and special character");
        }

        // Find and validate token (must search candidates due to hashing)
        // Note: We cannot directly lookup hashed token, must verify each candidate
        PasswordResetToken resetToken = passwordResetTokenRepository
                .findAllByExpiryDateAfter(LocalDateTime.now())
                .stream()
                .filter(t -> passwordEncoder.matches(token, t.getToken()))
                .findFirst()
                .orElseThrow(() -> {
                    log.warn("Invalid password reset token used");
                    securityEventService.logSecurityEvent(
                            null,
                            "PASSWORD_RESET_CONFIRM_FAILED",
                            "Invalid reset token",
                            httpRequest);
                    return new BadRequestException("Invalid or expired reset token");
                });

        // Check expiration
        if (resetToken.getExpiryDate().isBefore(LocalDateTime.now())) {
            securityEventService.logSecurityEvent(
                    resetToken.getAuthUser(),
                    "PASSWORD_RESET_CONFIRM_FAILED",
                    "Expired reset token used",
                    httpRequest);
            passwordResetTokenRepository.delete(resetToken);
            throw new BadRequestException("Invalid or expired reset token");
        }

        AuthUserCredentials user = resetToken.getAuthUser();

        // Check for failed verification attempts (brute force protection)
        if (isVerificationRateLimited(user.getAuthUserId())) {
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_CONFIRM_FAILED",
                    "Too many failed verification attempts",
                    httpRequest);
            throw new BadRequestException("Too many failed attempts. Please request a new password reset.");
        }

        // Check if new password is same as old
        if (passwordEncoder.matches(newPassword, user.getPasswordHash())) {
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_CONFIRM_FAILED",
                    "New password same as old password",
                    httpRequest);
            throw new BadRequestException("New password must be different from current password");
        }

        // Update password
        user.setPasswordHash(passwordEncoder.encode(newPassword));
        user.setUpdatedAt(LocalDateTime.now());
        userRepository.save(user);

        // Delete token
        passwordResetTokenRepository.delete(resetToken);

        entityManager.flush();

        securityEventService.logSecurityEvent(
                user,
                "PASSWORD_RESET_SUCCESS",
                "Password reset completed successfully",
                httpRequest);

        log.info("Password reset successful for user ID: {}", user.getAuthUserId());

        return RegistrationResponse.builder()
                .success(true)
                .message("Password reset successfully. Please login with your new password.")
                .build();
    }

    /**
     * Confirm password reset using OTP (for phone-based reset) and new password.
     */
    @Transactional(isolation = Isolation.SERIALIZABLE)
    public RegistrationResponse confirmPasswordResetWithOtp(
            String userContact,
            String otp,
            String newPassword,
            HttpServletRequest httpRequest) {

        securityEventService.logSecurityEvent(
                null,
                "PASSWORD_RESET_OTP_CONFIRM_ATTEMPT",
                "OTP-based password reset confirmation attempted for: " + maskContact(userContact),
                httpRequest);

        // Validate contact format
        ContactType contactType = determineContactType(userContact);
        if (contactType == null) {
            securityEventService.logSecurityEvent(
                    null,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "Invalid contact format provided",
                    httpRequest);
            throw new BadRequestException("Invalid email or phone number format");
        }

        // Validate password strength
        if (!isValidPassword(newPassword)) {
            securityEventService.logSecurityEvent(
                    null,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "Weak password provided",
                    httpRequest);
            throw new BadRequestException(
                    "Password must be at least 8 characters with uppercase, lowercase, number, and special character");
        }

        // Validate OTP format (must be 6 digits)
        if (otp == null || !otp.matches("^\\d{6}$")) {
            securityEventService.logSecurityEvent(
                    null,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "Invalid OTP format",
                    httpRequest);
            throw new BadRequestException("Invalid OTP format");
        }

        // Find user
        AuthUserCredentials user = userRepository.findByEmailOrPhoneNumber(userContact, userContact)
                .orElseThrow(() -> {
                    log.warn("Password reset OTP confirmation attempted for non-existent user: {}",
                            maskContact(userContact));
                    securityEventService.logSecurityEvent(
                            null,
                            "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                            "Non-existent user",
                            httpRequest);
                    return new BadRequestException("Invalid OTP or user not found");
                });

        // Check user status
        if (user.getStatus() == AuthUserCredentials.Status.SUSPENDED ||
                user.getStatus() == AuthUserCredentials.Status.LOCKED) {
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "Password reset attempted for suspended/locked account",
                    httpRequest);
            throw new BadRequestException("Account is suspended or locked");
        }

        // Check for failed verification attempts (brute force protection)
        if (isVerificationRateLimited(user.getAuthUserId())) {
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "Too many failed OTP verification attempts",
                    httpRequest);
            throw new BadRequestException("Too many failed attempts. Please request a new password reset.");
        }

        // Find valid OTP with pessimistic lock (prevents race conditions)
        var otpLog = otpEventLogRepository
                .findFirstByUserAndTypeForUpdate(
                        user.getAuthUserId(),
                        "PASSWORD_RESET",
                        LocalDateTime.now())
                .orElse(null);

        if (otpLog == null) {
            recordFailedVerificationAttempt(user.getAuthUserId());
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "No valid OTP found",
                    httpRequest);
            throw new BadRequestException("Invalid or expired OTP");
        }

        // Verify OTP
        if (!passwordEncoder.matches(otp, otpLog.getOtpCode())) {
            recordFailedVerificationAttempt(user.getAuthUserId());
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "OTP mismatch",
                    httpRequest);
            throw new BadRequestException("Invalid or expired OTP");
        }

        // Check if new password is same as old
        if (passwordEncoder.matches(newPassword, user.getPasswordHash())) {
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_OTP_CONFIRM_FAILED",
                    "New password same as old password",
                    httpRequest);
            throw new BadRequestException("New password must be different from current password");
        }

        // Update password
        user.setPasswordHash(passwordEncoder.encode(newPassword));
        user.setUpdatedAt(LocalDateTime.now());
        userRepository.save(user);

        // Mark OTP as used
        otpLog.setVerified(true);
        otpEventLogRepository.save(otpLog);

        entityManager.flush();

        securityEventService.logSecurityEvent(
                user,
                "PASSWORD_RESET_SUCCESS",
                "Password reset completed successfully via OTP",
                httpRequest);

        log.info("Password reset successful via OTP for user ID: {}", user.getAuthUserId());

        return RegistrationResponse.builder()
                .success(true)
                .message("Password reset successfully. Please login with your new password.")
                .build();
    }

    private RegistrationResponse handleEmailReset(AuthUserCredentials user, HttpServletRequest httpRequest) {
        try {
            // Generate cryptographically secure reset token
            String plainToken = generateSecureResetToken();

            // Hash token before storage (prevents plaintext exposure in DB breach)
            String hashedToken = passwordEncoder.encode(plainToken);

            // Save hashed token to database
            PasswordResetToken passwordResetToken = new PasswordResetToken();
            passwordResetToken.setToken(hashedToken);
            passwordResetToken.setAuthUser(user);
            passwordResetToken.setPurpose("PASSWORD_RESET");
            passwordResetToken.setUsed(false);
            passwordResetToken.setCreatedAt(LocalDateTime.now());
            passwordResetToken.setExpiryDate(LocalDateTime.now().plusHours(1));
            passwordResetTokenRepository.save(passwordResetToken);

            entityManager.flush();

            // Send plaintext token via email (user needs this to reset)
            emailService.sendPasswordResetEmail(user.getEmail(), plainToken, user.getAuthUserId())
                    .exceptionally(ex -> {
                        log.error("Failed to send password reset email to: {}", user.getEmail(), ex);
                        return null;
                    });

            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_EMAIL_SENT",
                    "Password reset email sent",
                    httpRequest);

            return RegistrationResponse.builder()
                    .success(true)
                    .email(user.getEmail())
                    .message("If this email exists in our system, you will receive a password reset link")
                    .build();

        } catch (Exception e) {
            log.error("Error sending password reset email: {}", e.getMessage(), e);
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_EMAIL_FAILED",
                    "Failed to send password reset email",
                    httpRequest);
            throw new RuntimeException("Unable to process password reset. Please try again later.");
        }
    }

    private RegistrationResponse handlePhoneReset(AuthUserCredentials user, HttpServletRequest httpRequest) {
        try {
            // Generate OTP
            String otp = otpService.generatePasswordResetOtp(user.getAuthUserId());

            // Send SMS (async)
            smsService.sendPasswordResetSms(user.getPhoneNumber(), otp, user.getAuthUserId())
                    .exceptionally(ex -> {
                        log.error("Failed to send password reset SMS to: {}", user.getPhoneNumber(), ex);
                        return null;
                    });

            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_SMS_SENT",
                    "Password reset OTP sent via SMS",
                    httpRequest);

            return RegistrationResponse.builder()
                    .success(true)
                    .message("If this phone number exists in our system, you will receive a password reset OTP")
                    .build();

        } catch (Exception e) {
            log.error("Error sending password reset SMS: {}", e.getMessage(), e);
            securityEventService.logSecurityEvent(
                    user,
                    "PASSWORD_RESET_SMS_FAILED",
                    "Failed to send password reset SMS",
                    httpRequest);
            throw new RuntimeException("Unable to process password reset. Please try again later.");
        }
    }

    private ContactType determineContactType(String contact) {
        if (contact == null || contact.trim().isEmpty()) {
            return null;
        }

        String trimmed = contact.trim();

        if (EMAIL_PATTERN.matcher(trimmed).matches()) {
            return ContactType.EMAIL;
        } else if (PHONE_PATTERN.matcher(trimmed).matches()) {
            return ContactType.PHONE;
        }

        return null;
    }

    private boolean isValidPassword(String password) {
        if (password == null || password.length() < 8) {
            return false;
        }
        return PASSWORD_PATTERN.matcher(password).matches();
    }

    private boolean isPasswordResetRateLimited(UUID userId) {
        LocalDateTime oneHourAgo = LocalDateTime.now().minusHours(1);
        long recentAttempts = passwordResetTokenRepository
                .countByAuthUser_AuthUserIdAndExpiryDateAfter(userId, oneHourAgo);
        return recentAttempts >= 3; // Max 3 reset attempts per hour
    }

    private void invalidateExistingTokens(UUID userId) {
        passwordResetTokenRepository.deleteAllByAuthUser_AuthUserId(userId);
    }

    private boolean isVerificationRateLimited(UUID userId) {
        LocalDateTime fifteenMinutesAgo = LocalDateTime.now().minusMinutes(15);
        // Count failed verification attempts in the last 15 minutes
        long failedAttempts = otpEventLogRepository
                .countByAuthUser_AuthUserIdAndOtpTypeAndCreatedAtAfter(
                        userId,
                        "PASSWORD_RESET_FAILED_VERIFICATION",
                        fifteenMinutesAgo);
        return failedAttempts >= MAX_VERIFICATION_ATTEMPTS;
    }

    private void recordFailedVerificationAttempt(UUID userId) {
        // Record failed attempt for rate limiting
        AuthUserCredentials user = userRepository.findById(userId).orElse(null);
        if (user != null) {
            OtpEventLog failedAttempt = OtpEventLog.builder()
                    .authUser(user)
                    .otpCode("FAILED_ATTEMPT")
                    .sentTo("N/A")
                    .otpType("PASSWORD_RESET_FAILED_VERIFICATION")
                    .createdAt(LocalDateTime.now())
                    .expiresAt(LocalDateTime.now().plusMinutes(15))
                    .verified(false)
                    .build();
            otpEventLogRepository.save(failedAttempt);
        }
    }

    private String maskContact(String contact) {
        if (contact == null || contact.length() < 4) {
            return "****";
        }
        if (contact.contains("@")) {
            String[] parts = contact.split("@");
            return parts[0].substring(0, Math.min(2, parts[0].length())) + "***@" + parts[1];
        } else {
            return contact.substring(0, Math.min(3, contact.length())) + "****";
        }
    }

    /**
     * Scheduled cleanup task for expired tokens and OTPs.
     * Runs every hour to prevent database bloat and improve query performance.
     */
    @Scheduled(cron = "0 0 * * * *") // Every hour at minute 0
    @Transactional
    public void cleanupExpiredTokensAndOtps() {
        try {
            LocalDateTime now = LocalDateTime.now();

            // Cleanup expired password reset tokens
            int deletedTokens = passwordResetTokenRepository.deleteAllByExpiryDateBefore(now);

            // Cleanup expired OTPs
            int deletedOtps = otpEventLogRepository.deleteAllByExpiresAtBefore(now);

            log.info("Cleanup completed: Deleted {} expired password reset tokens, {} expired OTPs",
                    deletedTokens, deletedOtps);

        } catch (Exception e) {
            log.error("Error during scheduled cleanup of expired tokens and OTPs", e);
            // Don't throw exception - scheduler will continue next iteration
        }
    }

    private enum ContactType {
        EMAIL, PHONE
    }
}
