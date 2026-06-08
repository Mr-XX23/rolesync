package com.medisecure.authservice.services.userregistration;

import com.medisecure.authservice.dto.userregistrations.RegistrationRequest;
import com.medisecure.authservice.dto.userregistrations.RegistrationResponse;
import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.services.*;
import jakarta.persistence.EntityManager;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.ConstraintViolationException;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Random;

@Service
@RequiredArgsConstructor
@Slf4j
public class Registration {

    private final AuthSecurityEventService securityEventService;
    private final UserRepository userRepository;
    private final EntityManager entityManager;
    private final OtpService otpService;
    private final EmailService emailService;
    private final SmsService smsService;
    private final PasswordEncoder passwordEncoder;

    private final Random random = new SecureRandom();
    private static final String PREFIX = "MS_";
    private static final int MAX_USERNAME_ATTEMPTS = 10;

    /**
     * Register a new user with email or phone number.
     * Ensures security events are only logged after successful database write.
     *
     * @param request The registration request containing user details.
     * @param httpRequest The HTTP request for security logging.
     * @return A response with registration status.
     */
    @Transactional
    public RegistrationResponse registerUser(@Valid RegistrationRequest request, HttpServletRequest httpRequest) {

        // Log security event for registration attempt
        securityEventService.logSecurityEvent(
                null,
                "USER_REGISTRATION_ATTEMPT",
                "A user registration attempt is made.",
                httpRequest);

        // Validate that at least one contact method is provided
        if (request.getEmail() == null && request.getPhoneNumber() == null) {
            securityEventService.logSecurityEvent(
                    null,
                    "USER_REGISTRATION_FAILED",
                    "Registration failed due to missing contact information.",
                    httpRequest);

            throw new BadRequestException("Either email or phone number must be provided");
        }

        // Determine primary login type
        AuthUserCredentials.LoginType loginType;
        if (request.getEmail() != null && request.getPhoneNumber() != null) {
            loginType = AuthUserCredentials.LoginType.BOTH;
        } else if (request.getEmail() != null) {
            loginType = AuthUserCredentials.LoginType.EMAIL;
        } else {
            loginType = AuthUserCredentials.LoginType.PHONE;
        }

        // Check if user already exists (without revealing which field exists)
        boolean exists = (request.getEmail() != null && userRepository.existsByEmail(request.getEmail()))
                || (request.getPhoneNumber() != null && userRepository.existsByPhoneNumber(request.getPhoneNumber()));

        if (exists) {
            log.warn("Registration attempt with existing credentials");

            securityEventService.logSecurityEvent(
                    null,
                    "USER_REGISTRATION_FAILED",
                    "Registration failed due to existing user credentials.",
                    httpRequest);

            // Return generic response for privacy
            return buildGenericResponse(loginType);
        }

        // Hash the password
        String passwordHash = passwordEncoder.encode(request.getPassword());

        // Create new auth user credentials
        AuthUserCredentials authUserCredentials = AuthUserCredentials.builder()
                .usernameId(generateUniqueUsername())
                .username(request.getUsername())
                .email(request.getEmail() != null ? request.getEmail() : "")
                .phoneNumber(request.getPhoneNumber() != null ? request.getPhoneNumber() : "")
                .passwordHash(passwordHash)
                .role(request.getRole())
                .loginType(loginType)
                .status(AuthUserCredentials.Status.INACTIVE)
                .isEmailVerified(false)
                .isPhoneVerified(false)
                .mfaEnabled(false)
                .createdAt(LocalDateTime.now())
                .updatedAt(LocalDateTime.now())
                .build();

        // Save to database with validation
        AuthUserCredentials savedUser;
        try {
            savedUser = userRepository.save(authUserCredentials);

           // Flush to ensure database constraints ( Errors ) are checked immediately
            entityManager.flush();

            log.info("User saved successfully with ID: {}", savedUser.getAuthUserId());

        } catch (DataIntegrityViolationException e) {
            // Specific catch for duplicate key violations
            log.error("Duplicate user credentials detected: {}", e.getMessage());

            securityEventService.logSecurityEvent(
                    null,
                    "USER_REGISTRATION_FAILED",
                    "Registration failed due to duplicate credentials.",
                    httpRequest);

            // Return generic response for privacy (don't reveal which field is duplicate)
            return buildGenericResponse(loginType);

        } catch (ConstraintViolationException e) {
            // Specific catch for validation errors
            log.error("Validation constraint violation: {}", e.getMessage());

            securityEventService.logSecurityEvent(
                    null,
                    "USER_REGISTRATION_FAILED",
                    "Registration failed due to validation error.",
                    httpRequest);

            throw new BadRequestException("Invalid user data provided");

        } catch (Exception e) {
            // Generic catch for other database errors
            log.error("Database error during user registration", e);

            securityEventService.logSecurityEvent(
                    null,
                    "USER_REGISTRATION_FAILED",
                    "Registration failed due to database error.",
                    httpRequest);

            throw new RuntimeException("Failed to register user. Please try again.");
        }

        // Log security event for successful registration
        securityEventService.logSecurityEvent(
                savedUser,
                "USER_REGISTRATION_SUCCESS",
                "A new user has been registered successfully.",
                httpRequest);

        // Send verification based on login type
        boolean emailSent = false;
        boolean smsSent = false;
        try {
            if (loginType == AuthUserCredentials.LoginType.EMAIL
                    || loginType == AuthUserCredentials.LoginType.BOTH) {
                String verificationToken = otpService.generateEmailVerificationToken(savedUser.getAuthUserId());
                emailService.sendVerificationEmail(savedUser.getEmail(), verificationToken,
                        savedUser.getAuthUserId());
                emailSent = true;
            }

            if (loginType == AuthUserCredentials.LoginType.PHONE
                    || loginType == AuthUserCredentials.LoginType.BOTH) {
                String otp = otpService.generatePhoneOtp(savedUser.getAuthUserId());
                smsService.sendOtpSms(savedUser.getPhoneNumber(), otp, savedUser.getAuthUserId());
                smsSent = true;
            }
        } catch (Exception e) {
            log.error("Failed to send verification for user {}: {}",
                    savedUser.getAuthUserId(), e.getMessage());
            emailSent = false;
            // Registration still succeeds - user can request new verification later
        }

        return RegistrationResponse.builder()
                .success(true)
                .message("Registration successful. Please verify your "
                        + (loginType == AuthUserCredentials.LoginType.EMAIL ? "email."
                        : (loginType == AuthUserCredentials.LoginType.BOTH) ? "email and phone number."
                        : "phone number."))
                .username(savedUser.getUsername())
                .userId(savedUser.getAuthUserId().toString())
                .email(savedUser.getEmail())
                .emailVerificationSent(emailSent)
                .smsVerificationSent(smsSent)
                .build();
    }

    /**
     * Builds a generic registration response to avoid revealing existing user details.
     *
     * @param loginType The type of login used (email or phone).
     * @return A generic RegistrationResponse.
     */
    private RegistrationResponse buildGenericResponse(AuthUserCredentials.LoginType loginType) {
        String message = loginType == AuthUserCredentials.LoginType.EMAIL
                ? "If this email is not registered, you will receive a verification email."
                : loginType == AuthUserCredentials.LoginType.BOTH
                ? "If these credentials are not registered, you will receive verification instructions."
                : "If this phone number is not registered, you will receive a verification SMS.";

//        // Return success response instead of throwing exception (better UX and privacy)
//        return RegistrationResponse.builder()
//                .success(true)
//                .message(message)
//                .build();

        throw new BadRequestException(message);
    }

    /**
     * Generates a unique username with the format "MS_" followed by 8 random
     * alphanumeric characters.
     *
     * @return A unique username.
     */
    private String generateUniqueUsername() {
        String username;
        int attempts = 0;

        do {
            String randomPart = generateRandomString(8);
            username = PREFIX + randomPart;
            attempts++;

            if (attempts >= MAX_USERNAME_ATTEMPTS) {
                // Fallback with timestamp if collision persists
                username = PREFIX + generateRandomString(6) + (System.currentTimeMillis() % 10000);
                log.warn("Username generation required {} attempts, using timestamp fallback", attempts);
            }
        } while (userRepository.existsByUsername(username));

        return username;
    }

    /**
     * Generates a random alphanumeric string of specified length.
     *
     * @param length The length of the random string.
     * @return A random alphanumeric string.
     */
    private String generateRandomString(int length) {
        String chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        StringBuilder sb = new StringBuilder(length);

        for (int i = 0; i < length; i++) {
            sb.append(chars.charAt(random.nextInt(chars.length())));
        }

        return sb.toString();
    }
}
