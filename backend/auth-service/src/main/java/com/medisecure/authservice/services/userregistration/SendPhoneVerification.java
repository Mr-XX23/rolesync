package com.medisecure.authservice.services.userregistration;

import com.medisecure.authservice.dto.userregistrations.RegistrationResponse;
import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.services.AuthSecurityEventService;
import com.medisecure.authservice.services.OtpService;
import com.medisecure.authservice.services.SmsService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class SendPhoneVerification {


    private final AuthSecurityEventService securityEventService;
    private final UserRepository userRepository;
    private final OtpService otpService;
    private final SmsService smsService;

    /**
     * Verifies user's phone number using the OTP.
     *
     * @param userId The ID of the user.
     * @return A response entity with verification status.
     */
    public RegistrationResponse sendPhoneVerification(UUID userId, HttpServletRequest httpRequest) {

        log.info("Sending phone verification to user ID: {}", userId);

        // Log security even
        securityEventService.logSecurityEvent(
                null,
                "PHONE_VERIFICATION",
                "A phone verification attempt is made to send OTP.",
                httpRequest);

        try {

            AuthUserCredentials user = userRepository.findById(userId)
                    .orElseThrow(() -> new RuntimeException("User not found"));

            if (user.isPhoneVerified()) {

                // Log security even
                securityEventService.logSecurityEvent(
                        null,
                        "PHONE_VERIFICATION",
                        "Phone verification attempt for already verified phone.",
                        httpRequest);

                throw new BadRequestException("Phone already verified");
            }

            if (user.getLoginType() == AuthUserCredentials.LoginType.BOTH && !user.isEmailVerified()) {
                // Log security even
                securityEventService.logSecurityEvent(
                        null,
                        "PHONE_VERIFICATION",
                        "Phone verification attempt before email is verified.",
                        httpRequest);

                throw new BadRequestException("Email should verified before phone verification");
            }

            String otp = otpService.generatePhoneOtp(userId);
            smsService.sendOtpSms(user.getPhoneNumber(), otp, userId);

            return RegistrationResponse.builder()
                    .success(true)
                    .username(user.getUsername())
                    .userId(user.getAuthUserId().toString())
                    .email(user.getEmail())
                    .message("OTP sent successfully")
                    .build();
        } catch (Exception e) {
            log.error("Error sending phone OTP: {}", e.getMessage());

            // Log security even
            securityEventService.logSecurityEvent(
                    null,
                    "PHONE_VERIFICATION",
                    "Error sending phone OTP.",
                    httpRequest);

            throw new RuntimeException("Error sending phone OTP. Please try again.");
        }
    }

}
