package com.medisecure.authservice.controllers;

import com.medisecure.authservice.annotations.RateLimited;
import com.medisecure.authservice.dto.email.EmailVerificationRequest;
import com.medisecure.authservice.dto.passwordreset.PasswordResetConfirmRequest;
import com.medisecure.authservice.dto.passwordreset.PasswordResetOtpConfirmRequest;
import com.medisecure.authservice.dto.passwordreset.PasswordResetRequest;
import com.medisecure.authservice.dto.phone.PhoneVerificationOtpRequest;
import com.medisecure.authservice.dto.phone.PhoneVerificationRequest;
import com.medisecure.authservice.dto.userregistrations.RegistrationRequest;
import com.medisecure.authservice.dto.userregistrations.RegistrationResponse;
import com.medisecure.authservice.services.userregistration.*;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.ModelAndView;

@RestController
@RequestMapping("/api/v1/auth")
@RequiredArgsConstructor
public class UserRegistration {

    private final Registration registrationService;
    private final SendEmailVerification sendEmailVerification;
    private final SendPhoneVerification sendPhoneVerification;
    private final VerifyEmail verifyEmail;
    private final VerifyPhone verifyPhone;
    private final ResetPassword resetPassword;

    /**
     * Register a new user with email or phone number.
     * 
     * @param request The registration request containing user details.
     * @return A response entity with registration status.
     */
    @PostMapping("/register")
    @RateLimited(maxRequests = 3, windowSeconds = 300, message = "Too many registration attempts. Please try again in 5 minutes.")
    public ResponseEntity<RegistrationResponse> registerUser(HttpServletRequest httpRequest,
            @Valid @RequestBody RegistrationRequest request) {

        RegistrationResponse response = registrationService.registerUser(request, httpRequest);
        return ResponseEntity.ok(response);
    }

    /**
     * Verify user's email address using the verification token.
     * 
     * @param request The verification request containing the userId.
     * @return A response entity with verification status.
     */
    @PostMapping("/send-email-verification")
    @RateLimited(maxRequests = 5, windowSeconds = 3600, message = "Too many verification emails sent. Please wait an hour.")
    public ResponseEntity<RegistrationResponse> sendEmailVerification(
            @Valid @RequestBody EmailVerificationRequest request, HttpServletRequest httpRequest) {
        RegistrationResponse response = sendEmailVerification.sendEmailVerification(request.getUserId(), httpRequest);
        return ResponseEntity.ok(response);
    }

    /**
     * Verify user's phone number using the OTP.
     * 
     * @param request The verification request containing userId.
     * @return A response entity with verification status.
     */
    @PostMapping("/send-phone-verification")
    @RateLimited(maxRequests = 5, windowSeconds = 3600, message = "Too many verification SMSs sent. Please wait an hour.")
    public ResponseEntity<RegistrationResponse> sendPhoneVerification(
            @Valid @RequestBody PhoneVerificationRequest request, HttpServletRequest httpRequest) {
        RegistrationResponse response = sendPhoneVerification.sendPhoneVerification(request.getUserId(), httpRequest);
        return ResponseEntity.ok(response);
    }

    /**
     * Verify user's email address using the verification token.
     * 
     * @param token The email verification token.
     * @return A ModelAndView with verification status page.
     */
    @GetMapping("/verify-email")
    public ModelAndView verifyEmail(@RequestParam("token") @NotBlank(message = "Token is required") String token,
            HttpServletRequest httpRequest) {
        return verifyEmail.verifyEmail(token, httpRequest);
    }

    /**
     * Verify user's phone number using the OTP.
     * 
     * @param request The verification request containing userId and OTP.
     * @return A response entity with verification status.
     */
    @PostMapping("/verify-phone")
    @RateLimited(maxRequests = 10, windowSeconds = 300, message = "Too many verification attempts. Please wait 5 minutes.")
    public ResponseEntity<RegistrationResponse> verifyPhone(
            @Valid @RequestBody PhoneVerificationOtpRequest request,
            HttpServletRequest httpRequest) {

        RegistrationResponse response = verifyPhone.verifyPhone(request.getOtp(), request.getUserId(), httpRequest);
        HttpStatus status = response.isSuccess() ? HttpStatus.OK : HttpStatus.BAD_REQUEST;
        return ResponseEntity.status(status).body(response);

    }

    /**
     * Password reset for user using email or phone.
     * 
     * @param request The password reset request containing email or phone number.
     * @return A response entity with verification status.
     */
    @PostMapping("/reset-password")
    @RateLimited(maxRequests = 3, windowSeconds = 3600, message = "Too many password reset requests. Please try again later.")
    public ResponseEntity<RegistrationResponse> resetPassword(
            @Valid @RequestBody PasswordResetRequest request, HttpServletRequest httpRequest) {
        RegistrationResponse response = resetPassword.resetPassword(request.getUserContact(), httpRequest);
        return ResponseEntity.ok(response);
    }

    /**
     * Confirm password reset for user using email or phone.
     * Token now passed in request body for security (not in URL).
     * 
     * @param request The confirmation request containing token and new password.
     * @return A response entity with verification status.
     */
    @PostMapping("/confirm-reset")
    @RateLimited(maxRequests = 5, windowSeconds = 300, message = "Too many password reset confirmation attempts. Please wait 5 minutes.")
    public ResponseEntity<RegistrationResponse> confirmPasswordReset(
            @Valid @RequestBody PasswordResetConfirmRequest request,
            HttpServletRequest httpRequest) {

        RegistrationResponse response = resetPassword.confirmPasswordReset(
                request.getToken(),
                request.getNewPassword(),
                httpRequest);
        HttpStatus status = response.isSuccess() ? HttpStatus.OK : HttpStatus.BAD_REQUEST;
        return ResponseEntity.status(status).body(response);
    }

    /**
     * Confirm password reset using OTP (for phone-based reset).
     * 
     * @param request The OTP confirmation request containing user contact, OTP, and
     *                new password.
     * @return A response entity with verification status.
     */
    @PostMapping("/confirm-reset-otp")
    @RateLimited(maxRequests = 5, windowSeconds = 300, message = "Too many OTP verification attempts. Please wait 5 minutes.")
    public ResponseEntity<RegistrationResponse> confirmPasswordResetWithOtp(
            @Valid @RequestBody PasswordResetOtpConfirmRequest request, HttpServletRequest httpRequest) {

        RegistrationResponse response = resetPassword.confirmPasswordResetWithOtp(
                request.getUserContact(),
                request.getOtp(),
                request.getNewPassword(),
                httpRequest);
        HttpStatus status = response.isSuccess() ? HttpStatus.OK : HttpStatus.BAD_REQUEST;
        return ResponseEntity.status(status).body(response);
    }

}
