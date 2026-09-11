package com.rolesync.authservice.services;

import com.rolesync.authservice.dto.email.EmailResponse;
import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertFalse;

/**
 * Offline guard tests for the welcome email: an account with no valid email
 * address (e.g. a phone-only sign-up) must be skipped gracefully — no send is
 * attempted and no exception escapes, so account activation is never blocked.
 *
 * These inputs short-circuit in isValidEmail() before any mail sender, template
 * engine or repository is touched, so the collaborators can be null here.
 */
class EmailServiceWelcomeTest {

    private final EmailService emailService = new EmailService(null, null, null);

    @Test
    void blankEmailIsSkipped() {
        EmailResponse resp = emailService.sendWelcomeEmail("", "Alice", UUID.randomUUID()).join();
        assertFalse(resp.isSuccess());
    }

    @Test
    void nullEmailIsSkipped() {
        EmailResponse resp = emailService.sendWelcomeEmail(null, "Alice", UUID.randomUUID()).join();
        assertFalse(resp.isSuccess());
    }

    @Test
    void malformedEmailIsSkipped() {
        EmailResponse resp = emailService.sendWelcomeEmail("not-an-email", "Alice", UUID.randomUUID()).join();
        assertFalse(resp.isSuccess());
    }
}
