package com.medisecure.authservice.services;

import org.springframework.http.ResponseCookie;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import jakarta.annotation.PostConstruct;
import java.time.Duration;

@Service
@Slf4j
public class CookiesService {

    @Value("${cookie.access-token-max-age:604800}")
    private int accessTokenMaxAge;

    @Value("${cookie.refresh-token-max-age:2592000}")
    private int refreshTokenMaxAge;

    @Value("${cookie.domain:localhost}")
    private String cookieDomain;

    @Value("${cookie.secure:true}")
    private boolean secure;

    @Value("${spring.profiles.active:dev}")
    private String activeProfile;

    /**
     * Validate cookie security configuration on startup.
     * Prevents insecure production deployments.
     */
    @PostConstruct
    public void validateConfiguration() {
        if (("prod".equalsIgnoreCase(activeProfile) || "production".equalsIgnoreCase(activeProfile)) && !secure) {
            throw new IllegalStateException(
                    "CRITICAL SECURITY ERROR: Cookie secure flag must be enabled in production! " +
                            "Set cookie.secure=true in application.properties");
        }

        if (!secure) {
            log.warn("⚠️ SECURITY WARNING: Cookies are configured with Secure=false. " +
                    "This is acceptable for local development but MUST be changed for production!");
        }

        log.info("Cookie configuration initialized - Secure: {}, Domain: {}, Profile: {}",
                secure, cookieDomain, activeProfile);
    }

    public void setAccessTokenCookie(HttpServletResponse response, String accessToken) {
        ResponseCookie cookie = createCookie("access_token", accessToken, accessTokenMaxAge);
        response.addHeader("Set-Cookie", cookie.toString());
        log.info("Access token cookie set successfully");
    }

    public void setRefreshTokenCookie(HttpServletResponse response, String refreshToken) {
        ResponseCookie cookie = createCookie("refresh_token", refreshToken, refreshTokenMaxAge);
        response.addHeader("Set-Cookie", cookie.toString());
        log.info("Refresh token cookie set successfully");
    }

    public void clearAccessTokenCookie(HttpServletResponse response) {
        ResponseCookie cookie = createCookie("access_token", null, 0);
        response.addHeader("Set-Cookie", cookie.toString());
        log.info("Access token cookie cleared");
    }

    public void clearRefreshTokenCookie(HttpServletResponse response) {
        ResponseCookie cookie = createCookie("refresh_token", null, 0);
        response.addHeader("Set-Cookie", cookie.toString());
        log.info("Refresh token cookie cleared");
    }

    public void clearAllTokenCookies(HttpServletResponse response) {
        clearAccessTokenCookie(response);
        clearRefreshTokenCookie(response);
        log.info("All token cookies cleared");
    }

    private ResponseCookie createCookie(String name, String value, int maxAge) {
        return ResponseCookie.from(name, value)
                .httpOnly(true) // Prevent XSS attacks
                .secure(secure) // HTTPS only (enforced in production)
                .path("/")
                .maxAge(Duration.ofSeconds(maxAge))
                .domain(cookieDomain)
                .sameSite("Strict") // Strict CSRF protection
                .build();
    }
}
