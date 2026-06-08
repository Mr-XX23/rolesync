package com.medisecure.authservice.services;

import com.medisecure.authservice.configurations.TwilioConfig;
import com.medisecure.authservice.dto.SmsRequest.SmsRequest;
import com.medisecure.authservice.dto.SmsRequest.SmsResponse;
import com.medisecure.authservice.models.SmsEventLog;
import com.medisecure.authservice.repository.SmsEventLogRepository;
import com.twilio.exception.ApiException;
import com.twilio.exception.TwilioException;
import com.twilio.rest.api.v2010.account.Message;
import com.twilio.type.PhoneNumber;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.retry.annotation.Backoff;
import org.springframework.retry.annotation.Recover;
import org.springframework.retry.annotation.Retryable;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Matcher;

@Service
@RequiredArgsConstructor
@Slf4j
public class SmsService {

    private final TwilioConfig twilioConfig;
    private final SmsEventLogRepository smsEventLogRepository;

    @Value("${sms.rate.limit.per-hour:5}")
    private int rateLimitPerHour;

    @Value("${sms.rate.limit.per-day:20}")
    private int rateLimitPerDay;

    @Value("${sms.max.retry.attempts:3}")
    private int maxRetryAttempts;

    @Value("${sms.otp.rate.limit.per-hour:3}")
    private int otpRateLimitPerHour;

    @Value("${app.name:MediSecure}")
    private String appName;

    private static final java.util.regex.Pattern E164_PATTERN = java.util.regex.Pattern.compile("^\\+[1-9]\\d{1,14}$");
    private static final java.util.regex.Pattern PHONE_DIGITS_PATTERN = java.util.regex.Pattern.compile("\\d+");

    // Blocked/Invalid country codes for security
    private static final List<String> BLOCKED_COUNTRY_CODES = Arrays.asList(
            "+850", // North Korea
            "+963" // Syria
    );

    /**
     * Sends OTP SMS to user's phone number
     * 
     * @param phoneNumber Recipient phone number in E.164 format
     * @param otp         OTP code to send
     */
    @Async
    // Note: @Transactional removed from async method (incompatible with @Async)
    // Repository save operations in sendSmsWithRetry() create their own
    // transactions
    public CompletableFuture<SmsResponse> sendOtpSms(
            @Pattern(regexp = "^\\+?[1-9]\\d{1,14}$", message = "Invalid phone number format") @NotBlank String phoneNumber,
            @NotBlank String otp,
            @NotBlank UUID authUserId) {

        try {
            // Normalize phone number
            String normalizedPhone = normalizePhoneNumber(phoneNumber);

            // Validate phone number
            if (!isValidPhoneNumber(normalizedPhone)) {
                log.error("Invalid phone number format: {}", phoneNumber);
                return CompletableFuture.completedFuture(
                        SmsResponse.builder()
                                .success(false)
                                .message("Invalid phone number format")
                                .build());
            }

            // Check rate limiting for OTP
            if (isOtpRateLimited(normalizedPhone)) {
                log.warn("OTP rate limit exceeded for phone: {}", maskPhoneNumber(normalizedPhone));
                return CompletableFuture.completedFuture(
                        SmsResponse.builder()
                                .success(false)
                                .message("Too many OTP requests. Please try again later.")
                                .build());
            }

            // Build OTP message
            String message = String.format(
                    "Your %s verification code is: %s\n\nThis code will expire in 15 minutes.\n\nIf you didn't request this code, please ignore this message.",
                    appName,
                    otp);

            // Create SMS request
            SmsRequest request = SmsRequest.builder()
                    .to(normalizedPhone)
                    .message(message)
                    .fromNumber(twilioConfig.getFromPhoneNumber())
                    .build();

            // Send SMS
            return sendSmsWithRetry(request, SmsEventLog.SmsType.OTP_VERIFICATION, authUserId, true);

        } catch (Exception e) {
            log.error("Unexpected error sending OTP SMS to: {}", maskPhoneNumber(phoneNumber), e);
            return CompletableFuture.completedFuture(
                    SmsResponse.builder()
                            .success(false)
                            .message("Failed to send OTP SMS")
                            .build());
        }
    }

    /**
     * Sends password reset OTP via SMS
     * 
     * @param phoneNumber Recipient phone number
     * @param otp         Reset OTP
     * @param authUserId  User ID
     */
    @Async
    // Note: @Transactional removed from async method (incompatible with @Async)
    // Repository save operations in sendSmsWithRetry() create their own
    // transactions
    public CompletableFuture<SmsResponse> sendPasswordResetSms(
            @Pattern(regexp = "^\\+?[1-9]\\d{1,14}$", message = "Invalid phone number format") String phoneNumber,
            @NotBlank String otp,
            UUID authUserId) {

        try {
            String normalizedPhone = normalizePhoneNumber(phoneNumber);

            if (!isValidPhoneNumber(normalizedPhone) || isOtpRateLimited(normalizedPhone)) {
                return CompletableFuture.completedFuture(
                        SmsResponse.builder()
                                .success(false)
                                .message("Unable to send password reset SMS")
                                .build());
            }

            String message = String.format(
                    "Your %s password reset code is: %s\n\nThis code expires in 15 minutes.\n\nIf you didn't request this, please ignore this message.",
                    appName,
                    otp);

            SmsRequest request = SmsRequest.builder()
                    .to(normalizedPhone)
                    .message(message)
                    .fromNumber(twilioConfig.getFromPhoneNumber())
                    .build();

            return sendSmsWithRetry(request, SmsEventLog.SmsType.PASSWORD_RESET, authUserId, true);

        } catch (Exception e) {
            log.error("Error sending password reset SMS to: {}", maskPhoneNumber(phoneNumber), e);
            return CompletableFuture.completedFuture(
                    SmsResponse.builder()
                            .success(false)
                            .message("Failed to send password reset SMS")
                            .build());
        }
    }

    /**
     * Generic method to send SMS with retry mechanism
     * 
     * @param request    SMS request details
     * @param smsType    Type of SMS
     * @param authUserId User ID (optional)
     * @param isOtp      Whether this is an OTP message
     */
    @Retryable(retryFor = { TwilioException.class,
            ApiException.class }, maxAttempts = 3, backoff = @Backoff(delay = 3000, multiplier = 2))
    @Transactional
    public CompletableFuture<SmsResponse> sendSmsWithRetry(
            @Valid SmsRequest request,
            SmsEventLog.SmsType smsType,
            UUID authUserId,
            boolean isOtp) {

        SmsEventLog eventLog = null;

        try {
            // Check general rate limiting
            if (!isOtp && isGeneralRateLimited(request.getTo())) {
                log.warn("General SMS rate limit exceeded for phone: {}", maskPhoneNumber(request.getTo()));
                return CompletableFuture.completedFuture(
                        SmsResponse.builder()
                                .success(false)
                                .message("SMS rate limit exceeded. Please try again later.")
                                .build());
            }

            // Extract country code
            String countryCode = extractCountryCode(request.getTo());

            // Create event log entry
            eventLog = SmsEventLog.builder()
                    .recipient(request.getTo())
                    .fromNumber(request.getFromNumber() != null ? request.getFromNumber()
                            : twilioConfig.getFromPhoneNumber())
                    .messageContent(request.getMessage())
                    .smsType(smsType)
                    .status(SmsEventLog.SmsStatus.PENDING)
                    .createdAt(LocalDateTime.now())
                    .authUserId(authUserId)
                    .isOtp(isOtp)
                    .countryCode(countryCode)
                    .retryAttempts(0)
                    .build();

            eventLog = smsEventLogRepository.save(eventLog);

            // Send SMS via Twilio
            Message message = Message.creator(
                    new PhoneNumber(request.getTo()),
                    new PhoneNumber(eventLog.getFromNumber()),
                    request.getMessage()).create();

            log.info(String.valueOf(message));

            // Update event log with success
            eventLog.setMessageSid(message.getSid());
            eventLog.setStatus(mapTwilioStatus(message.getStatus()));
            eventLog.setSentAt(LocalDateTime.now());

            if (message.getPrice() != null) {
                try {
                    eventLog.setCost(new BigDecimal(message.getPrice()));
                } catch (NumberFormatException e) {
                    log.warn("Failed to parse SMS price: {}", message.getPrice());
                }
            }

            smsEventLogRepository.save(eventLog);

            log.info("SMS sent successfully to: {} with SID: {}",
                    maskPhoneNumber(request.getTo()), message.getSid());

            return CompletableFuture.completedFuture(
                    SmsResponse.builder()
                            .success(true)
                            .message("SMS sent successfully")
                            .messageSid(message.getSid())
                            .status(message.getStatus().toString())
                            .sentAt(LocalDateTime.now())
                            .retryAttempts(eventLog.getRetryAttempts())
                            .cost(message.getPrice() != null ? new BigDecimal(message.getPrice()) : null)
                            .build());

        } catch (ApiException e) {
            log.error("Twilio API error sending SMS to: {} - Code: {}, Message: {}",
                    maskPhoneNumber(request.getTo()), e.getCode(), e.getMessage());

            if (eventLog != null) {
                eventLog.setStatus(SmsEventLog.SmsStatus.FAILED);
                eventLog.setErrorMessage(e.getMessage());
                eventLog.setErrorCode(String.valueOf(e.getCode()));
                eventLog.setRetryAttempts(eventLog.getRetryAttempts() + 1);
                smsEventLogRepository.save(eventLog);
            }

            // Check if error is retryable
            if (isRetryableError(e.getCode())) {
                throw e; // Trigger retry
            }

            return CompletableFuture.completedFuture(
                    SmsResponse.builder()
                            .success(false)
                            .message("SMS delivery failed: " + e.getMessage())
                            .errorCode(String.valueOf(e.getCode()))
                            .build());

        } catch (TwilioException e) {
            log.error("Twilio error sending SMS to: {}", maskPhoneNumber(request.getTo()), e);

            if (eventLog != null) {
                eventLog.setStatus(SmsEventLog.SmsStatus.FAILED);
                eventLog.setErrorMessage(e.getMessage());
                eventLog.setRetryAttempts(eventLog.getRetryAttempts() + 1);
                smsEventLogRepository.save(eventLog);
            }

            throw e; // Trigger retry

        } catch (Exception e) {
            log.error("Unexpected error sending SMS to: {}", maskPhoneNumber(request.getTo()), e);

            if (eventLog != null) {
                eventLog.setStatus(SmsEventLog.SmsStatus.FAILED);
                eventLog.setErrorMessage(e.getMessage());
                smsEventLogRepository.save(eventLog);
            }

            throw new RuntimeException("SMS sending failed", e);
        }
    }

    /**
     * Recovery method when all retries fail
     */
    @Recover
    public CompletableFuture<SmsResponse> recoverFromSmsFailure(
            Exception e,
            SmsRequest request,
            SmsEventLog.SmsType smsType,
            Long authUserId,
            boolean isOtp) {

        log.error("All retry attempts failed for SMS to: {}", maskPhoneNumber(request.getTo()), e);

        return CompletableFuture.completedFuture(
                SmsResponse.builder()
                        .success(false)
                        .message("Failed to send SMS after multiple attempts")
                        .retryAttempts(maxRetryAttempts)
                        .build());
    }

    /**
     * Normalizes phone number to E.164 format
     */
    private String normalizePhoneNumber(String phoneNumber) {
        if (phoneNumber == null) {
            return null;
        }

        // Remove all non-digit characters except +
        String cleaned = phoneNumber.replaceAll("[^\\d+]", "");

        // If no + prefix, assume nepali number and add +977
        if (!cleaned.startsWith("+")) {
            // Extract only digits
            Matcher matcher = PHONE_DIGITS_PATTERN.matcher(cleaned);
            if (matcher.find()) {
                String digits = matcher.group();
                // If it's 10 digits, assume nepali number
                if (digits.length() == 10) {
                    cleaned = "+977" + digits;
                } else if (digits.length() > 10) {
                    cleaned = "+" + digits;
                }
            }
        }

        return cleaned;
    }

    /**
     * Validates phone number format and security checks
     */
    private boolean isValidPhoneNumber(String phoneNumber) {
        if (phoneNumber == null || phoneNumber.trim().isEmpty()) {
            return false;
        }

        // Check E.164 format
        if (!E164_PATTERN.matcher(phoneNumber).matches()) {
            log.warn("Phone number does not match E.164 format: {}", maskPhoneNumber(phoneNumber));
            return false;
        }

        // Check length (E.164 max is 15 digits including country code)
        if (phoneNumber.length() > 16) { // +15 digits
            log.warn("Phone number exceeds maximum length: {}", maskPhoneNumber(phoneNumber));
            return false;
        }

        // Check blocked country codes
        for (String blockedCode : BLOCKED_COUNTRY_CODES) {
            if (phoneNumber.startsWith(blockedCode)) {
                log.warn("Blocked country code detected: {}", maskPhoneNumber(phoneNumber));
                return false;
            }
        }

        return true;
    }

    /**
     * Checks if phone number has exceeded OTP rate limit
     */
    private boolean isOtpRateLimited(String phoneNumber) {
        LocalDateTime oneHourAgo = LocalDateTime.now().minusHours(1);
        long otpCount = smsEventLogRepository.countByRecipientAndCreatedAtAfter(phoneNumber, oneHourAgo);

        return otpCount >= otpRateLimitPerHour;
    }

    /**
     * Checks if phone number has exceeded general SMS rate limit
     */
    private boolean isGeneralRateLimited(String phoneNumber) {
        LocalDateTime oneHourAgo = LocalDateTime.now().minusHours(1);
        long hourlyCount = smsEventLogRepository.countByRecipientAndCreatedAtAfter(phoneNumber, oneHourAgo);

        if (hourlyCount >= rateLimitPerHour) {
            return true;
        }

        LocalDateTime oneDayAgo = LocalDateTime.now().minusDays(1);
        long dailyCount = smsEventLogRepository.countByRecipientAndCreatedAtAfter(phoneNumber, oneDayAgo);

        return dailyCount >= rateLimitPerDay;
    }

    /**
     * Maps Twilio status to internal status
     */
    private SmsEventLog.SmsStatus mapTwilioStatus(Message.Status twilioStatus) {
        return switch (twilioStatus) {
            case QUEUED -> SmsEventLog.SmsStatus.QUEUED;
            case SENT, SENDING -> SmsEventLog.SmsStatus.SENT;
            case DELIVERED -> SmsEventLog.SmsStatus.DELIVERED;
            case FAILED -> SmsEventLog.SmsStatus.FAILED;
            case UNDELIVERED -> SmsEventLog.SmsStatus.UNDELIVERED;
            default -> SmsEventLog.SmsStatus.PENDING;
        };
    }

    /**
     * Checks if Twilio error code is retryable
     */
    private boolean isRetryableError(int errorCode) {
        // Retryable error codes
        List<Integer> retryableCodes = Arrays.asList(
                20429, // Too Many Requests
                30001, // Queue overflow
                30002, // Account suspended
                30003, // Unreachable destination handset
                30005, // Unknown destination handset
                30006 // Landline or unreachable carrier
        );

        return retryableCodes.contains(errorCode);
    }

    /**
     * Extracts country code from phone number
     */
    private String extractCountryCode(String phoneNumber) {
        if (phoneNumber == null || !phoneNumber.startsWith("+")) {
            return null;
        }

        // Extract first 1-3 digits after +
        String digits = phoneNumber.substring(1);
        if (digits.length() >= 1) {
            // Try 3 digits first (e.g., +234 for Nigeria)
            if (digits.length() >= 3) {
                return "+" + digits.substring(0, 3);
            } else if (digits.length() >= 2) {
                return "+" + digits.substring(0, 2);
            } else {
                return "+" + digits.substring(0, 1);
            }
        }

        return null;
    }

    /**
     * Masks phone number for logging (security)
     */
    private String maskPhoneNumber(String phoneNumber) {
        if (phoneNumber == null || phoneNumber.length() < 4) {
            return "****";
        }

        int visibleDigits = 4;
        int length = phoneNumber.length();
        String lastDigits = phoneNumber.substring(length - visibleDigits);

        return "*".repeat(length - visibleDigits) + lastDigits;
    }

    /**
     * Gets SMS sending statistics for a phone number
     */
    public Map<String, Object> getSmsStats(String phoneNumber) {
        String normalized = normalizePhoneNumber(phoneNumber);

        LocalDateTime oneHourAgo = LocalDateTime.now().minusHours(1);
        LocalDateTime oneDayAgo = LocalDateTime.now().minusDays(1);

        long hourlyCount = smsEventLogRepository.countByRecipientAndCreatedAtAfter(normalized, oneHourAgo);
        long dailyCount = smsEventLogRepository.countByRecipientAndCreatedAtAfter(normalized, oneDayAgo);

        Map<String, Object> stats = new HashMap<>();
        stats.put("recipient", maskPhoneNumber(normalized));
        stats.put("smsSentLastHour", hourlyCount);
        stats.put("smsSentLast24Hours", dailyCount);
        stats.put("hourlyRateLimit", rateLimitPerHour);
        stats.put("dailyRateLimit", rateLimitPerDay);
        stats.put("otpHourlyRateLimit", otpRateLimitPerHour);

        return stats;
    }

    /**
     * Updates SMS delivery status (webhook callback)
     */
    @Transactional
    public void updateSmsStatus(String messageSid, String status) {
        smsEventLogRepository.findByMessageSid(messageSid).ifPresent(eventLog -> {
            try {
                Message.Status twilioStatus = Message.Status.forValue(status);
                eventLog.setStatus(mapTwilioStatus(twilioStatus));

                if (twilioStatus == Message.Status.DELIVERED) {
                    eventLog.setDeliveredAt(LocalDateTime.now());
                }

                smsEventLogRepository.save(eventLog);
                log.info("Updated SMS status for SID: {} to {}", messageSid, status);

            } catch (Exception e) {
                log.error("Failed to update SMS status for SID: {}", messageSid, e);
            }
        });
    }
}