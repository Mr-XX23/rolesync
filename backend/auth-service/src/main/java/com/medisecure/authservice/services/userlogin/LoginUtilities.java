package com.medisecure.authservice.services.userlogin;

import com.medisecure.authservice.models.AuthSecurityEvent;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.AuthSecurityEventRepository;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

@RequiredArgsConstructor
@Slf4j
@Component
public class LoginUtilities {

    private final AuthSecurityEventRepository securityEvents;

    // Save login event into database
    public void saveLoginEvent(AuthUserCredentials user, String eventType, String eventData, String ipAddress, String userAgent) {
        AuthSecurityEvent loginEvent = AuthSecurityEvent.builder()
                .authUser(user)
                .eventType(eventType)
                .eventData(eventData)
                .eventTime(LocalDateTime.now())
                .ipAddress(ipAddress)
                .userAgent(userAgent)
                .build();

        try {
            AuthSecurityEvent savedEvent = securityEvents.save(loginEvent);
            log.info("Saved login event with id: {}", savedEvent.getEventId());
        } catch (Exception e) {
            log.error("Failed to save security event: {}", e.getMessage());
        }
    }

    // Get client IP address from request
    public String getClientIpAddress(HttpServletRequest request) {
        String xForwardedFor = request.getHeader("X-Forwarded-For");
        if (xForwardedFor != null && !xForwardedFor.isEmpty()) {
            return xForwardedFor.split(",")[0].trim();
        }

        String xRealIp = request.getHeader("X-Real-IP");
        if (xRealIp != null && !xRealIp.isEmpty()) {
            return xRealIp;
        }

        return request.getRemoteAddr();
    }
}
