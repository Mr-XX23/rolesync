package com.medisecure.authservice.services.userregistration;

import com.medisecure.authservice.dto.userregistrations.RegistrationResponse;
import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.models.OtpEventLog;
import com.medisecure.authservice.repository.OtpEventLogRepository;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.services.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.NotBlank;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class VerifyPhone {

        private final UserRepository userRepository;
        private final PasswordEncoder passwordEncoder;
        private final OtpEventLogRepository otpEventLogRepository;
        private final AuthSecurityEventService securityEventService;

        /**
         * Verify user's phone using the verification token.
         *
         * @param token  The phone verification OTP.
         * @param userId The user ID as string.
         */
        @Transactional
        public RegistrationResponse verifyPhone(
                        @NotBlank(message = "Token is required") String token,
                        @NotBlank(message = "User ID is required") String userId,
                        HttpServletRequest httpRequest) {

                // Log attempt
                securityEventService.logSecurityEvent(
                                null,
                                "PHONE_VERIFICATION_ATTEMPT",
                                "A phone verification attempt is made to activate account.",
                                httpRequest);

                // Parse userId
                final UUID userUuid;
                try {
                        userUuid = UUID.fromString(userId);
                } catch (IllegalArgumentException ex) {
                        log.error("Invalid user ID format: {}", userId);
                        securityEventService.logSecurityEvent(
                                        null,
                                        "PHONE_VERIFICATION_FAILED",
                                        "Invalid user ID format during phone verification attempt.",
                                        httpRequest);
                        throw new BadRequestException("Invalid user ID format");
                }

                // Load user
                AuthUserCredentials user = userRepository.findById(userUuid)
                                .orElseThrow(() -> {
                                        log.warn("Phone verification for non-existing user {}", userUuid);
                                        securityEventService.logSecurityEvent(
                                                        null,
                                                        "PHONE_VERIFICATION_FAILED",
                                                        "Phone verification attempt for non-existing user.",
                                                        httpRequest);
                                        return new BadRequestException("User not found");
                                });

                // Already verified
                if (user.isPhoneVerified()) {
                        securityEventService.logSecurityEvent(
                                        user,
                                        "PHONE_VERIFICATION_FAILED",
                                        "Phone verification attempt for already verified phone.",
                                        httpRequest);
                        throw new BadRequestException("Phone already verified");
                }

                // BOTH: email must be verified first
                if (user.getLoginType() == AuthUserCredentials.LoginType.BOTH && !user.isEmailVerified()) {
                        securityEventService.logSecurityEvent(
                                        user,
                                        "PHONE_VERIFICATION_FAILED",
                                        "Phone verification attempt before email is verified.",
                                        httpRequest);
                        throw new BadRequestException("Email must be verified before phone verification");
                }

                // Load latest valid OTP for this user and type
                OtpEventLog otpLog = otpEventLogRepository
                                .findFirstByAuthUser_AuthUserIdAndOtpTypeAndVerifiedFalseAndExpiresAtAfter(
                                                userUuid,
                                                "PHONE_VERIFICATION",
                                                LocalDateTime.now())
                                .orElse(null);

                if (otpLog == null) {
                        securityEventService.logSecurityEvent(
                                        user,
                                        "PHONE_VERIFICATION_FAILED",
                                        "Invalid or expired phone verification token.",
                                        httpRequest);
                        throw new BadRequestException("Invalid or expired token");
                }

                // Verify OTP (bcrypt)
                if (!passwordEncoder.matches(token, otpLog.getOtpCode())) {
                        securityEventService.logSecurityEvent(
                                        user,
                                        "PHONE_VERIFICATION_FAILED",
                                        "Invalid phone verification token (mismatch).",
                                        httpRequest);
                        throw new BadRequestException("Invalid or expired token");
                }

                // Update user flags
                user.setPhoneVerified(true);

                boolean shouldActivate = false;
                if (user.getLoginType() == AuthUserCredentials.LoginType.PHONE) {
                        user.setStatus(AuthUserCredentials.Status.ACTIVE);
                        shouldActivate = true;
                } else if (user.getLoginType() == AuthUserCredentials.LoginType.BOTH && user.isEmailVerified()) {
                        user.setStatus(AuthUserCredentials.Status.ACTIVE);
                        shouldActivate = true;
                }

                user.setUpdatedAt(LocalDateTime.now());
                otpLog.setVerified(true);

                try {
                        // Persist changes
                        userRepository.save(user);
                        otpEventLogRepository.save(otpLog);

                } catch (Exception e) {
                        log.error("Database error during phone verification for user {}: {}", userUuid, e.getMessage(),
                                        e);
                        securityEventService.logSecurityEvent(
                                        user,
                                        "PHONE_VERIFICATION_FAILED",
                                        "Phone verification failed due to database error.",
                                        httpRequest);
                        throw new RuntimeException("Error verifying phone. Please try again.");
                }

                // Success event (only after DB updates succeed)
                securityEventService.logSecurityEvent(
                                user,
                                "PHONE_VERIFICATION_SUCCESS",
                                "Phone verified successfully" + (shouldActivate ? " and account activated." : "."),
                                httpRequest);

                return RegistrationResponse.builder()
                                .success(true)
                                .message("Phone verified successfully" +
                                                (user.getStatus() == AuthUserCredentials.Status.ACTIVE
                                                                ? ". Your account is now active."
                                                                : ". Please verify your email to activate your account."))
                                .username(user.getUsername())
                                .userId(user.getAuthUserId().toString())
                                .build();
        }
}