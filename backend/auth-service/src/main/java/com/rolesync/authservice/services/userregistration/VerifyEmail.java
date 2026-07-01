package com.rolesync.authservice.services.userregistration;

import com.rolesync.authservice.models.AuthUserCredentials;
import com.rolesync.authservice.models.OtpEventLog;
import com.rolesync.authservice.repository.OtpEventLogRepository;
import com.rolesync.authservice.repository.UserRepository;
import com.rolesync.authservice.services.AuthSecurityEventService;
import com.rolesync.authservice.services.HashFormater;
import jakarta.persistence.EntityManager;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.servlet.ModelAndView;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import com.rolesync.authservice.services.SseNotificationService;
import com.rolesync.authservice.services.OtpService;
import com.rolesync.authservice.services.SmsService;
import java.util.UUID;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
@Slf4j
public class VerifyEmail {

    private final UserRepository userRepository;
    private final OtpEventLogRepository otpEventLogRepository;
    private final HashFormater hashFormater;
    private final EntityManager entityManager;
    private final AuthSecurityEventService securityEventService;
    private final SseNotificationService sseNotificationService;
    private final OtpService otpService;
    private final SmsService smsService;
    private final com.rolesync.authservice.kafka.producer.AuthEventPublisher authEventPublisher;

    @Value("${app.frontend.url:http://localhost:3000}")
    private String frontendUrl;

    /**
     * Verify user's email address using the verification token.
     *
     * @param token The email verification token.
     * @return A ModelAndView with verification status page.
     */

    @Transactional
    public ModelAndView verifyEmail(@NotBlank(message = "Token is required") String token, HttpServletRequest httpRequest) {

        // Log security even
        securityEventService.logSecurityEvent(
                null,
                "EMAIL_VERIFICATION",
                "An email verification attempt is made for activations of account.",
                httpRequest);

        log.info("Validating email verification token: {}", token);

        // Validate token is not empty
        if (token == null || token.isBlank()) {
            securityEventService.logSecurityEvent(
                    null,
                    "EMAIL_VERIFICATION_FAILED",
                    "Email verification failed: empty token.",
                    httpRequest);

            ModelAndView modelAndView = new ModelAndView("email-verification-success");
            modelAndView.addObject("success", false);
            modelAndView.addObject("title", "Invalid Verification Link");
            modelAndView.addObject("message", "The verification link is invalid or incomplete.");
            modelAndView.addObject("subMessage", "Please request a new verification email.");
            modelAndView.addObject("loginUrl", frontendUrl + "/login");
            return modelAndView;
        }

        try {

            log.info("Hashing the token to match the stored hash for email verification.");
            // Hash the token to match stored hash
            String tokenHash = hashFormater.hashWithSHA256(token);

            // Find OTP log entry
            OtpEventLog otpLog = otpEventLogRepository
                    .findFirstByOtpTypeAndOtpCodeAndVerifiedAndExpiresAtAfter(
                            "EMAIL_VERIFICATION",
                            tokenHash,
                            false,
                            LocalDateTime.now()
                    )
                    .orElse(null);

            if (otpLog == null) {

                // Log security even
                securityEventService.logSecurityEvent(
                        null,
                        "EMAIL_VERIFICATION",
                        "Invalid email verification attempt.",
                        httpRequest);

                return getModelAndView();
            }

            // Get user
            AuthUserCredentials user = otpLog.getAuthUser();

            // Check if email is already verified
            if (user.isEmailVerified()) {
                log.info("Email already verified for user: {}", user.getAuthUserId());

                securityEventService.logSecurityEvent(
                        user,
                        "EMAIL_VERIFICATION_DUPLICATE",
                        "Email verification attempted for already verified email.",
                        httpRequest);

                return getModelAndView(user);
            }

            // Update user verification status
            user.setEmailVerified(true);

            // If user only has email (not BOTH), activate account
            if (user.getLoginType() == AuthUserCredentials.LoginType.EMAIL) {
                user.setStatus(AuthUserCredentials.Status.ACTIVE);
            }

            // If user has BOTH and phone is already verified, activate account
            if (user.getLoginType() == AuthUserCredentials.LoginType.BOTH && user.isPhoneVerified()) {
                user.setStatus(AuthUserCredentials.Status.ACTIVE);
            }

            // Update the updatedAt timestamp
            user.setUpdatedAt(LocalDateTime.now());

            // Mark OTP as verified
            otpLog.setVerified(true);

            // Save changes to database with validation
            try {
                userRepository.save(user);
                otpEventLogRepository.save(otpLog);

                // Force flush to catch database errors immediately
                entityManager.flush();

                log.info("Email verified successfully for user: {}", user.getAuthUserId());

                // Trigger after-commit logic for SMS OTP and SSE notification
                final UUID userId = user.getAuthUserId();
                final String userPhone = user.getPhoneNumber();
                final boolean hasPhone = user.getLoginType() == AuthUserCredentials.LoginType.BOTH;
                if (TransactionSynchronizationManager.isSynchronizationActive()) {
                    TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                        @Override
                        public void afterCommit() {
                            if (hasPhone) {
                                try {
                                    String otp = otpService.generatePhoneOtpRequiresNew(userId);
                                    smsService.sendOtpSms(userPhone, otp, userId);
                                    log.info("Sent phone verification OTP to user: {} after email verification commit", userId);
                                } catch (Exception e) {
                                    log.error("Failed to send phone OTP after email verification commit for user: {}", userId, e);
                                }
                            } else {
                                try {
                                    authEventPublisher.publishUserRegistered(user);
                                } catch (Exception e) {
                                    log.error("Failed to publish USER_REGISTERED event after email verification commit for user: {}", userId, e);
                                }
                            }
                            sseNotificationService.notifyEmailVerified(userId, hasPhone);
                        }
                    });
                } else {
                    if (hasPhone) {
                        try {
                            String otp = otpService.generatePhoneOtpRequiresNew(userId);
                            smsService.sendOtpSms(userPhone, otp, userId);
                        } catch (Exception e) {
                            log.error("Failed to send phone OTP for user: {}", userId, e);
                        }
                    } else {
                        try {
                            authEventPublisher.publishUserRegistered(user);
                        } catch (Exception e) {
                            log.error("Failed to publish USER_REGISTERED event for user: {}", userId, e);
                        }
                    }
                    sseNotificationService.notifyEmailVerified(userId, hasPhone);
                }

            } catch (DataIntegrityViolationException e) {
                log.error("Database constraint violation during email verification: {}", e.getMessage());

                securityEventService.logSecurityEvent(
                        user,
                        "EMAIL_VERIFICATION_FAILED",
                        "Email verification failed: database constraint violation.",
                        httpRequest);

                throw new RuntimeException("Failed to verify email. Please try again.");

            } catch (Exception e) {
                log.error("Database error during email verification for user {}: {}",
                        user.getAuthUserId(), e.getMessage());

                securityEventService.logSecurityEvent(
                        user,
                        "EMAIL_VERIFICATION_FAILED",
                        "Email verification failed: database error.",
                        httpRequest);

                throw new RuntimeException("Failed to verify email. Please try again.");
            }

            // Log success event
            securityEventService.logSecurityEvent(
                    user,
                    "EMAIL_VERIFICATION_SUCCESS",
                    "Email verified successfully" + (user.getStatus() == AuthUserCredentials.Status.ACTIVE
                            ? ". Account is now active."
                            : ". Phone verification pending to activate account."),
                    httpRequest);


            return getAndView(user);
        } catch (Exception e) {
            log.error("Error verifying email: {}", e.getMessage());

            // Log security even
            securityEventService.logSecurityEvent(
                    null,
                    "EMAIL_VERIFICATION",
                    "Error verifying email.",
                    httpRequest);

            ModelAndView modelAndView = new ModelAndView("email-verification-success");
            modelAndView.addObject("success", false);
            modelAndView.addObject("title", "Verification Error");
            modelAndView.addObject("message", "An error occurred while verifying your email.");
            modelAndView.addObject("subMessage", "Please try again or contact support if the problem persists.");
            modelAndView.addObject("loginUrl", frontendUrl + "/login");
            return modelAndView;
        }
    }

    private ModelAndView getAndView(AuthUserCredentials user) {
        ModelAndView modelAndView = new ModelAndView("email-verification-success");
        modelAndView.addObject("success", true);
        modelAndView.addObject("title", "Email Verified!");
        modelAndView.addObject("message", "Your email has been successfully verified" +
                (user.getStatus() == AuthUserCredentials.Status.ACTIVE
                        ? " and your account is now active."
                        : "."));
        modelAndView.addObject("subMessage", user.getStatus() != AuthUserCredentials.Status.ACTIVE
                ? "Please verify your phone number to activate your account and access full features."
                : "You can now log in to your account and start using our services.");
        modelAndView.addObject("loginUrl", frontendUrl + "/login");
        return modelAndView;
    }

    private ModelAndView getModelAndView(AuthUserCredentials user) {
        ModelAndView modelAndView = new ModelAndView("email-verification-success");
        modelAndView.addObject("success", true);
        modelAndView.addObject("title", "Email Already Verified");
        modelAndView.addObject("message", "Your email has already been verified" +
                (user.getStatus() == AuthUserCredentials.Status.ACTIVE
                        ? " and your account is active."
                        : "."));
        modelAndView.addObject("subMessage", user.getStatus() != AuthUserCredentials.Status.ACTIVE
                ? "Please verify your phone number to activate your account."
                : "You can now log in to your account.");
        modelAndView.addObject("loginUrl", frontendUrl + "/login");
        return modelAndView;
    }

    private ModelAndView getModelAndView() {
        ModelAndView modelAndView = new ModelAndView("email-verification-success");
        modelAndView.addObject("success", false);
        modelAndView.addObject("title", "Verification Failed");
        modelAndView.addObject("message", "The verification link is invalid or has expired.");
        modelAndView.addObject("subMessage", "Please request a new verification email from your account.");
        modelAndView.addObject("loginUrl", frontendUrl + "/login");
        return modelAndView;
    }


}
