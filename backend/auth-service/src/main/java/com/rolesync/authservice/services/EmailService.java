package com.rolesync.authservice.services;

import com.rolesync.authservice.dto.email.EmailRequest;
import com.rolesync.authservice.dto.email.EmailResponse;
import com.rolesync.authservice.models.EmailEventLog;
import com.rolesync.authservice.repository.EmailEventLogRepository;
import jakarta.mail.MessagingException;
import jakarta.mail.internet.MimeMessage;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.MailException;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.retry.annotation.Backoff;
import org.springframework.retry.annotation.Recover;
import org.springframework.retry.annotation.Retryable;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
@Slf4j
public class EmailService {

    private final JavaMailSender mailSender;
    private final EmailEventLogRepository emailEventLogRepository;
    private final TemplateEngine templateEngine;

    @Value("${spring.mail.username}")
    private String fromEmail;

    @Value("${app.name:RoleSync}")
    private String appName;

    @Value("${app.url}")
    private String appUrl;

    @Value("${app.frontend.url:http://localhost:5173}")
    private String frontendUrl;

    @Value("${email.verification.url-pattern}")
    private String verificationUrlPattern;

    @Value("${email.rate.limit.per-hour:10}")
    private int rateLimit;

    @Value("${email.max.retry.attempts:3}")
    private int maxRetryAttempts;

    private static final Pattern EMAIL_PATTERN = Pattern.compile(
            "^[A-Za-z0-9+_.-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$");

    @Async
    // Note: @Transactional removed from async method (incompatible)
    // Repository save operations create their own transactions
    public CompletableFuture<EmailResponse> sendVerificationEmail(
            @Email @NotBlank(message = "Email is mandatory") String email, @NotBlank String verificationToken,
            UUID authUserId) {

        try {
            // Validate email format
            if (!isValidEmail(email)) {
                log.error("Invalid email format: {}", email);
                return CompletableFuture.completedFuture(
                        EmailResponse.builder()
                                .success(false)
                                .message("Invalid email format")
                                .build());
            }

            // Check rate limiting
            if (isRateLimited(email)) {
                log.warn("Rate limit exceeded for email: {}", email);
                return CompletableFuture.completedFuture(
                        EmailResponse.builder()
                                .success(false)
                                .message("Too many emails sent. Please try again later.")
                                .build());
            }

            // Build verification link
            String verificationLink = String.format(verificationUrlPattern, appUrl, verificationToken);

            // Prepare template variables
            Map<String, Object> variables = new HashMap<>();
            variables.put("appName", appName);
            variables.put("verificationLink", verificationLink);
            variables.put("expiryMinutes", 15);

            // Create email request
            EmailRequest request = EmailRequest.builder()
                    .to(email)
                    .subject(String.format("Verify Your %s Account", appName))
                    .templateName("email-verification")
                    .templateVariables(variables)
                    .isHtml(true)
                    .build();

            // Send email
            return sendEmailWithRetry(request, EmailEventLog.EmailType.VERIFICATION, authUserId);

        } catch (Exception e) {
            log.error("Unexpected error sending verification email to: {}", email, e);
            return CompletableFuture.completedFuture(
                    EmailResponse.builder()
                            .success(false)
                            .message("Failed to send verification email")
                            .build());
        }
    }

    @Async
    // Note: @Transactional removed from async method (incompatible)
    public CompletableFuture<EmailResponse> sendPasswordResetEmail(@Email String email, @NotBlank String resetToken,
            UUID authUserId) {
        try {
            if (!isValidEmail(email) || isRateLimited(email)) {
                return CompletableFuture.completedFuture(
                        EmailResponse.builder()
                                .success(false)
                                .message("Unable to send password reset email")
                                .build());
            }

            String resetLink = String.format("%s/set-password?token=%s", frontendUrl, resetToken);

            Map<String, Object> variables = new HashMap<>();
            variables.put("appName", appName);
            variables.put("resetLink", resetLink);
            variables.put("expiryMinutes", 60);

            EmailRequest request = EmailRequest.builder()
                    .to(email)
                    .subject(String.format("Reset Your %s Password", appName))
                    .templateName("password-reset")
                    .templateVariables(variables)
                    .isHtml(true)
                    .build();

            return sendEmailWithRetry(request, EmailEventLog.EmailType.PASSWORD_RESET, authUserId);

        } catch (Exception e) {
            log.error("Error sending password reset email to: {}", email, e);
            return CompletableFuture.completedFuture(
                    EmailResponse.builder()
                            .success(false)
                            .message("Failed to send password reset email")
                            .build());
        }
    }

    @Retryable(retryFor = { MailException.class,
            MessagingException.class }, maxAttempts = 3, backoff = @Backoff(delay = 2000, multiplier = 2))
    @Transactional
    public CompletableFuture<EmailResponse> sendEmailWithRetry(@Valid EmailRequest request,
            EmailEventLog.EmailType emailType, UUID authUserId) {
        String messageId = UUID.randomUUID().toString();
        EmailEventLog eventLog = null;

        try {
            // Create event log entry
            eventLog = EmailEventLog.builder()
                    .recipient(request.getTo())
                    .subject(request.getSubject())
                    .emailType(emailType)
                    .status(EmailEventLog.EmailStatus.PENDING)
                    .messageId(messageId)
                    .createdAt(LocalDateTime.now())
                    .authUserId(authUserId)
                    .retryAttempts(0)
                    .build();

            eventLog = emailEventLogRepository.save(eventLog);

            // Create MIME message
            MimeMessage mimeMessage = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(
                    mimeMessage,
                    MimeMessageHelper.MULTIPART_MODE_MIXED_RELATED,
                    StandardCharsets.UTF_8.name());

            helper.setFrom(fromEmail, appName);
            helper.setTo(request.getTo());
            helper.setSubject(request.getSubject());

            if (request.getReplyTo() != null) {
                helper.setReplyTo(request.getReplyTo());
            }

            // Process content
            String content;
            if (request.getTemplateName() != null) {
                content = processTemplate(request.getTemplateName(), request.getTemplateVariables());
            } else if (request.getHtmlContent() != null) {
                content = request.getHtmlContent();
            } else {
                content = request.getPlainTextContent();
            }

            helper.setText(content, request.isHtml());

            // Send email
            mailSender.send(mimeMessage);

            // Update event log
            eventLog.setStatus(EmailEventLog.EmailStatus.SENT);
            eventLog.setUpdatedAt(LocalDateTime.now());
            emailEventLogRepository.save(eventLog);

            log.info("Email sent successfully to: {} with messageId: {}", request.getTo(), messageId);

            return CompletableFuture.completedFuture(
                    EmailResponse.builder()
                            .success(true)
                            .message("Email sent successfully")
                            .messageId(messageId)
                            .sentAt(LocalDateTime.now())
                            .retryAttempts(eventLog.getRetryAttempts())
                            .build());
        } catch (MailException | MessagingException e) {
            log.error("Failed to send email to: {} - Error: {}", request.getTo(), e.getMessage(), e);

            if (eventLog != null) {
                eventLog.setStatus(EmailEventLog.EmailStatus.FAILED);
                eventLog.setErrorMessage(e.getMessage());
                eventLog.setRetryAttempts(eventLog.getRetryAttempts() + 1);
                eventLog.setUpdatedAt(LocalDateTime.now());
                emailEventLogRepository.save(eventLog);
            }

            throw new RuntimeException("Email sending failed", e);

        } catch (Exception e) {
            log.error("Unexpected error sending email to: {}", request.getTo(), e);

            if (eventLog != null) {
                eventLog.setStatus(EmailEventLog.EmailStatus.FAILED);
                eventLog.setErrorMessage(e.getMessage());
                eventLog.setUpdatedAt(LocalDateTime.now());
                emailEventLogRepository.save(eventLog);
            }

            throw new RuntimeException("Email sending failed", e);
        }
    }

    @Recover
    public CompletableFuture<EmailResponse> recoverFromEmailFailure(Exception e, EmailRequest request,
            EmailEventLog.EmailType emailType, Long authUserId) {

        log.error("All retry attempts failed for email to: {}", request.getTo(), e);

        return CompletableFuture.completedFuture(
                EmailResponse.builder()
                        .success(false)
                        .message("Failed to send email after multiple attempts")
                        .retryAttempts(maxRetryAttempts)
                        .build());
    }

    private String processTemplate(String templateName, Map<String, Object> variables) {
        Context context = new Context();
        if (variables != null) {
            context.setVariables(variables);
        }
        return templateEngine.process(templateName, context);
    }

    private boolean isValidEmail(String email) {
        if (email == null || email.trim().isEmpty()) {
            return false;
        }

        // Basic format check
        if (!EMAIL_PATTERN.matcher(email).matches()) {
            return false;
        }

        // Additional security checks
        String lowerEmail = email.toLowerCase();

        // Check for common disposable email domains
        String[] disposableDomains = { "tempmail.com", "throwaway.email", "guerrillamail.com" };
        for (String domain : disposableDomains) {
            if (lowerEmail.endsWith("@" + domain)) {
                log.warn("Disposable email detected: {}", email);
                return false;
            }
        }

        return true;
    }

    private boolean isRateLimited(String email) {
        LocalDateTime oneHourAgo = LocalDateTime.now().minusHours(1);
        long emailCount = emailEventLogRepository.countByRecipientAndCreatedAtAfter(email, oneHourAgo);

        return emailCount >= rateLimit;
    }

    public Map<String, Object> getEmailStats(String email) {
        LocalDateTime oneDayAgo = LocalDateTime.now().minusDays(1);
        long recentEmails = emailEventLogRepository.countByRecipientAndCreatedAtAfter(email, oneDayAgo);

        Map<String, Object> stats = new HashMap<>();
        stats.put("recipient", email);
        stats.put("emailsSentLast24Hours", recentEmails);
        stats.put("rateLimitPerHour", rateLimit);

        return stats;
    }
}
