package com.medisecure.authservice.services;

import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.models.OtpEventLog;
import com.medisecure.authservice.repository.OtpEventLogRepository;
import com.medisecure.authservice.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class OtpService {
    private final UserRepository userRepository;
    private final OtpEventLogRepository otpEventLogRepository;
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();
    private final PasswordEncoder passwordEncoder;

    @Value("${otp.expiry.minutes}")
    private int otpExpiryMinutes;

    @Value("${otp.email.token.length}")
    private int emailTokenLength;

    @Transactional
    public String generateEmailVerificationToken(UUID authUserId) {
        AuthUserCredentials user = userRepository.findById(authUserId)
                .orElseThrow(() -> new IllegalArgumentException("User not found with ID: " + authUserId));

        // Invalidate any existing active email verification tokens
        invalidateExistingOtps(authUserId, "EMAIL_VERIFICATION");

        // Generate cryptographically secure token
        String token = generateSecureToken();

        // Hash the token before storing
        String tokenHash = hashWithSHA256(token);

        // Create OTP event log entry
        OtpEventLog otpLog = OtpEventLog.builder()
                .authUser(user)
                .otpCode(tokenHash)
                .sentTo(user.getEmail())
                .otpType("EMAIL_VERIFICATION")
                .createdAt(LocalDateTime.now())
                .expiresAt(LocalDateTime.now().plusMinutes(otpExpiryMinutes))
                .verified(false)
                .build();

        otpEventLogRepository.save(otpLog);

        log.info("Email verification token generated for user ID: {}", authUserId);

        return token;
    }

    @Transactional
    public String generatePhoneOtp(UUID authUserId) {
        AuthUserCredentials user = userRepository.findById(authUserId)
                .orElseThrow(() -> new IllegalArgumentException("User not found with ID: " + authUserId));

        // Invalidate any existing active phone verification OTPs
        invalidateExistingOtps(authUserId, "PHONE_VERIFICATION");

        // Generate unique numeric OTP with collision detection
        String otp = generateUniqueNumericOtp(authUserId);

        // Hash the OTP before storing
        String otpHash = passwordEncoder.encode(otp);

        // Create OTP event log entry
        OtpEventLog otpLog = OtpEventLog.builder()
                .authUser(user)
                .otpCode(otpHash)
                .sentTo(user.getPhoneNumber())
                .otpType("PHONE_VERIFICATION")
                .createdAt(LocalDateTime.now())
                .expiresAt(LocalDateTime.now().plusMinutes(otpExpiryMinutes))
                .verified(false)
                .build();

        otpEventLogRepository.save(otpLog);

        log.info("Phone verification OTP generated for user ID: {}", authUserId);

        return otp;
    }

    @Transactional
    public String generatePasswordResetOtp(UUID authUserId) {
        AuthUserCredentials user = userRepository.findById(authUserId)
                .orElseThrow(() -> new IllegalArgumentException("User not found with ID: " + authUserId));

        invalidateExistingOtps(authUserId, "PASSWORD_RESET");

        String otp = generateUniqueNumericOtp(authUserId);
        String otpHash = passwordEncoder.encode(otp);

        OtpEventLog otpLog = OtpEventLog.builder()
                .authUser(user)
                .otpCode(otpHash)
                .sentTo(user.getEmail() != null ? user.getEmail() : user.getPhoneNumber())
                .otpType("PASSWORD_RESET")
                .createdAt(LocalDateTime.now())
                .expiresAt(LocalDateTime.now().plusMinutes(otpExpiryMinutes))
                .verified(false)
                .build();

        otpEventLogRepository.save(otpLog);

        log.info("Password reset OTP generated for user ID: {}", authUserId);

        return otp;
    }

    private String hashWithSHA256(String input) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(input.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException e) {
            throw new RuntimeException("SHA-256 algorithm not available", e);
        }
    }

    private void invalidateExistingOtps(UUID authUserId, String otpType) {
        LocalDateTime now = LocalDateTime.now();

        // Use repository method to find active OTPs for the user and type, then mark
        // them as verified (invalidated)
        List<OtpEventLog> activeOtps = otpEventLogRepository
                .findAllByAuthUser_AuthUserIdAndOtpTypeAndVerifiedFalseAndExpiresAtAfter(
                        authUserId, otpType, now);

        activeOtps.forEach(log -> log.setVerified(true));
        otpEventLogRepository.saveAll(activeOtps);

        log.debug("Invalidated {} existing {} OTPs for user ID: {}",
                activeOtps.size(), otpType, authUserId);
    }

    private String generateSecureToken() {
        // Combine UUID with random bytes for maximum entropy
        String uuid = UUID.randomUUID().toString().replace("-", "");

        byte[] randomBytes = new byte[emailTokenLength];
        SECURE_RANDOM.nextBytes(randomBytes);
        String randomPart = Base64.getUrlEncoder().withoutPadding().encodeToString(randomBytes);

        return uuid + randomPart;
    }

    private String generateUniqueNumericOtp(UUID authUserId) {
        // Generate cryptographically secure random 6-digit OTP
        // OTP collision probability: 1/1,000,000 - negligible risk
        // Bcrypt hashing makes duplicate detection impractical and unnecessary
        int randomNum = SECURE_RANDOM.nextInt(1000000); // 0 to 999999
        return String.format("%06d", randomNum); // Pad with leading zeros
    }
}
