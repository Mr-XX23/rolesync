package com.medisecure.authservice.services;

import com.medisecure.authservice.dto.loginregistration.OAuth2LoginResponse;
import com.medisecure.authservice.exceptions.BadRequestException;
import com.medisecure.authservice.models.AuthUserCredentials;

import com.medisecure.authservice.repository.UserRepository;


import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.stereotype.Service;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class OAuth2Service {

    private final UserRepository userRepository;
    private final JwtService jwtService;
    private final CookiesService cookiesService;
    private final TokenService tokenService;
    private final AuthSecurityEventService securityEvents;
    private final EntityManager entityManager;

    @Transactional
    public OAuth2LoginResponse processOAuth2Login( OAuth2User oauth2User, HttpServletResponse response, HttpServletRequest request ){

        // Add null check
        if (oauth2User == null) {
            log.error("OAuth2User is null");
            throw new BadRequestException("OAuth2 authentication failed");
        }

        String email = oauth2User.getAttribute("email");
        String name = oauth2User.getAttribute("name");
        String googleId = oauth2User.getAttribute("sub");

        if (email == null || googleId == null) {
            log.error("Missing required OAuth2 attributes. Email: {}, GoogleId: {}", email, googleId);
            throw new BadRequestException("Invalid Google OAuth response - missing required information");
        }

        // Find or create user
        AuthUserCredentials user = userRepository.findByEmail(email)
                .orElseGet(() -> createNewOAuthUser(email, name, googleId));

        // Update Google ID if not set
        if (user.getGoogleId() == null) {
            user.setGoogleId(googleId);
            user.setEmailVerified(true);
            userRepository.save(user);
        }

        // Validate user status
        validateUserStatus(user);

        // Generate tokens
        String accessToken = jwtService.generateAccessToken(user);
        String refreshToken = jwtService.generateRefreshToken(user);

        // Save tokens in database
        tokenService.saveAccessToken(user.getAuthUserId(), accessToken);
        tokenService.saveRefreshToken(user.getAuthUserId(), refreshToken);

        // Force flush
        entityManager.flush();

        // Set HttpOnly cookies
        cookiesService.setAccessTokenCookie(response, accessToken);
        cookiesService.setRefreshTokenCookie(response, refreshToken);

        // Update last login
        user.setLastLoginAt(LocalDateTime.now());
        userRepository.save(user);

        // Log security event
        securityEvents.logSecurityEvent(
                user,
                "OAUTH2_LOGIN",
                "User logged in via Google OAuth2",
                request
        );

        boolean isNewUser = user.getCreatedAt().isAfter(LocalDateTime.now().minusSeconds(10));

        return OAuth2LoginResponse.builder()
                .accessToken(accessToken)
                .refreshToken(refreshToken)
                .userId(user.getAuthUserId().toString())
                .email(email)
                .name(name)
                .isNewUser(isNewUser)
                .message(isNewUser ? "Account created successfully" : "Login successful")
                .build();
    }

    private AuthUserCredentials createNewOAuthUser(String email, String name, String googleId) {
        AuthUserCredentials newUser = AuthUserCredentials.builder()
                .authUserId(UUID.randomUUID())
                .username(name)
                .email(email)
                .googleId(googleId)
                .isEmailVerified(true)
                .status(AuthUserCredentials.Status.ACTIVE)
                .loginType(AuthUserCredentials.LoginType.THIRD_PARTY)
                .createdAt(LocalDateTime.now())
                .updatedAt(LocalDateTime.now())
                .build();

        return userRepository.save(newUser);
    }

    private void validateUserStatus(AuthUserCredentials user) {
        if (user.getStatus() == AuthUserCredentials.Status.SUSPENDED) {
            throw new BadRequestException("Account is suspended");
        }
        if (user.getStatus() == AuthUserCredentials.Status.LOCKED) {
            throw new BadRequestException("Account has been deleted");
        }
    }
}
