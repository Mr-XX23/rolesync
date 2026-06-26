package com.medisecure.authservice.services.userregistration;

import com.medisecure.authservice.dto.userregistrations.RegistrationResponse;
import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.services.AuthSecurityEventService;
import com.medisecure.authservice.services.EmailService;
import com.medisecure.authservice.services.OtpService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class SendEmailVerification {

    private final AuthSecurityEventService securityEventService;
    private final UserRepository userRepository;
    private final OtpService otpService;
    private final EmailService emailService;

    /**
     * Verifies user's email address using the verification token.
     *
     * @param userId The email verification token.
     * @return A response entity with verification status.
     */

    @Transactional
    public RegistrationResponse sendEmailVerification(UUID userId, HttpServletRequest httpRequest) {
        try {

            // Log security even
            securityEventService.logSecurityEvent(
                    null,
                    "EMAIL_VERIFICATION",
                    "An email verification attempt is made to send verification link.",
                    httpRequest);

            AuthUserCredentials user = userRepository.findById(userId)
                    .orElseThrow(() -> new RuntimeException("User not found"));

            if (user.isEmailVerified()) {

                // Log security even
                securityEventService.logSecurityEvent(
                        null,
                        "EMAIL_VERIFICATION",
                        "Email verification attempt for already verified email.",
                        httpRequest);

                throw new BadRequestException("Email already verified");
            }

            String token = otpService.generateEmailVerificationToken(userId);
            emailService.sendVerificationEmail(user.getEmail(), token, userId);

            return RegistrationResponse.builder()
                    .success(true)
                    .email(user.getEmail())
                    .userId(user.getAuthUserId().toString())
                    .username(user.getUsername())
                    .message("Verification email sent successfully")
                    .build();

        } catch (Exception e) {
            log.error("Error sending verification email: {}", e.getMessage());

            // Log security even
            securityEventService.logSecurityEvent(
                    null,
                    "EMAIL_VERIFICATION",
                    "Error sending verification email.",
                    httpRequest);

            throw new BadRequestException("Error sending verification email. Please try again.");
        }
    }

}
