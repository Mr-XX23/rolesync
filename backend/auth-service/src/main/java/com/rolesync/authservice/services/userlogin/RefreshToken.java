package com.medisecure.authservice.services.userlogin;

import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.exceptions.ForbiddenException;
import com.medisecure.authservice.models.AuthUserCredentials;
import com.medisecure.authservice.repository.UserRepository;
import com.medisecure.authservice.services.CookiesService;
import com.medisecure.authservice.services.JwtService;
import com.medisecure.authservice.services.TokenService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Set;

@Service
@RequiredArgsConstructor
@Slf4j
public class RefreshToken {

    private final UserRepository userRepository;

    private final JwtService jwtService;
    private final TokenService tokenService;
    private final CookiesService cookiesService;
    private final LoginUtilities loginUtilities;

    // Refresh Access Token
    @Transactional
    public String refreshAccessToken(String refreshToken, HttpServletResponse response, HttpServletRequest request) {

        String ipAddress = loginUtilities.getClientIpAddress(request);
        String userAgent = request.getHeader("User-Agent");

        try {
            // Validate refresh token
            if (!tokenService.isTokenValid(refreshToken)) {
                log.error("Invalid or expired refresh token");
                throw new ForbiddenException("Invalid or expired refresh token, Please Login again");
            }

            // Decode token to get user ID
            String userId = jwtService.extractUserId(refreshToken);

            // Fetch user from database
            AuthUserCredentials user = userRepository.findById(java.util.UUID.fromString(userId))
                    .orElseThrow(() -> {
                        log.error("User not found with ID: {}", userId);
                        return new BadRequestException("User not found");
                    });

            // Check if user is still active
            if (Set.of(AuthUserCredentials.Status.LOCKED, AuthUserCredentials.Status.SUSPENDED)
                    .contains(user.getStatus())) {
                log.error("User account is locked or suspended: {}", user.getUsername());
                loginUtilities.saveLoginEvent(user, "FAILED_TOKEN_REFRESH",
                        "Account is " + user.getStatus().name().toLowerCase(), ipAddress, userAgent);
                throw new ForbiddenException("Account is blocked or suspended");
            }

            // Generate new access token
            String newAccessToken = jwtService.generateAccessToken(user);

            // Save new access token in database
            tokenService.saveAccessToken(user.getAuthUserId(), newAccessToken);

            // Set new Cookies
            cookiesService.setAccessTokenCookie(response, newAccessToken);

            // Log token refresh event
            loginUtilities.saveLoginEvent(user, "TOKEN_REFRESH_SUCCESS", "Tokens refreshed successfully", ipAddress,
                    userAgent);

            log.info("Generated new access token for user ID: {}", userId);
            return newAccessToken;
        } catch (Exception e) {
            log.error("Error refreshing access token: {}", e.getMessage());
            throw new BadRequestException("Error refreshing access token");
        }
    }

}
