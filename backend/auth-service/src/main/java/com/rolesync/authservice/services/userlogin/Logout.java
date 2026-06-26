package com.medisecure.authservice.services.userlogin;

import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.services.AuthSecurityEventService;
import com.medisecure.authservice.services.CookiesService;
import com.medisecure.authservice.services.JwtService;
import com.medisecure.authservice.services.TokenService;
import jakarta.persistence.EntityManager;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class Logout {

    private final UserRepository userRepository;

    private final JwtService jwtService;
    private final TokenService tokenService;
    private final CookiesService cookiesService;
    private final LoginUtilities loginUtilities;
    private final AuthSecurityEventService securityEventService;
    private final EntityManager entityManager;

    /**
     * Logout user by revoking all their tokens at once (more efficient).
     */
    @Transactional
    public String logout(String accessToken, String refreshToken,
                       HttpServletRequest request, HttpServletResponse response) {

        String ipAddress = loginUtilities.getClientIpAddress(request);
        String userAgent = request.getHeader("User-Agent");

        UUID userId = null;
        AuthUserCredentials user = null;

        try {
            if (accessToken != null && !accessToken.isBlank()) {
                String userIdStr = jwtService.extractUserId(accessToken);
                userId = UUID.fromString(userIdStr);
                user = userRepository.findById(userId).orElse(null);
            }
        } catch (Exception e) {
            log.warn("Could not extract user from token during logout: {}", e.getMessage());
        }

        securityEventService.logSecurityEvent(
                user,
                "LOGOUT_ATTEMPT",
                "User logout attempt initiated.",
                request);

        // Revoke all user tokens efficiently (single DB query)
        boolean tokensRevoked = false;
        if (userId != null) {
            try {
                tokenService.revokeAllUserTokens(userId);
                entityManager.flush();
                tokensRevoked = true;
            } catch (Exception e) {
                log.error("Error revoking tokens for user {}: {}", userId, e.getMessage(), e);
                securityEventService.logSecurityEvent(
                        user,
                        "LOGOUT_TOKEN_REVOCATION_FAILED",
                        "Token revocation failed: " + e.getMessage(),
                        request);
            }
        }

        // Always clear cookies
        cookiesService.clearAllTokenCookies(response);

        // Log result
        if (tokensRevoked) {
            loginUtilities.saveLoginEvent(user, "LOGOUT_SUCCESS",
                    "User logged out successfully", ipAddress, userAgent);
            securityEventService.logSecurityEvent(user, "LOGOUT_SUCCESS",
                    "User logged out successfully.", request);
            log.info("User {} logged out successfully",
                    user != null ? user.getUsername() : "unknown");

            return "Logged out successfully";
        } else {
            loginUtilities.saveLoginEvent(user, "LOGOUT_PARTIAL",
                    "Logout completed but token revocation may have failed", ipAddress, userAgent);
            securityEventService.logSecurityEvent(user, "LOGOUT_PARTIAL",
                    "Logout completed but some operations failed.", request);
            log.warn("Logout completed with issues for user {}",
                    user != null ? user.getUsername() : "unknown");
            return "Logged out, but some operations may have failed";
        }
    }

    @Transactional
    public void forceLogoutAllSessions(String userId, String reason) {
        try {
            // Revoke all tokens for the user
            tokenService.revokeAllUserTokens(java.util.UUID.fromString(userId));

            // Fetch user
            AuthUserCredentials user = userRepository.findById(java.util.UUID.fromString(userId))
                    .orElse(null);

            // Log forced logout event
            loginUtilities.saveLoginEvent(user, "FORCED_LOGOUT", "All sessions terminated. Reason: " + reason, "SYSTEM", "SYSTEM");

            log.info("All sessions terminated for user ID: {}", userId);

        } catch (Exception e) {
            log.error("Error forcing logout for user {}: {}", userId, e.getMessage());
        }
    }

}
