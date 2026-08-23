package com.rolesync.authservice.services;

import com.rolesync.authservice.dto.loginregistration.OAuth2LoginResponse;
import com.rolesync.authservice.exceptions.BadRequestException;
import com.rolesync.authservice.exceptions.ForbiddenException;
import com.rolesync.authservice.kafka.producer.AuthEventPublisher;
import com.rolesync.authservice.models.AuthUserCredentials;
import com.rolesync.authservice.models.Role;
import com.rolesync.authservice.repository.UserRepository;
import jakarta.persistence.EntityManager;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.oauth2.core.user.OAuth2User;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Random;
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
    private final AuthEventPublisher authEventPublisher;
    private final EntityManager entityManager;

    private final Random random = new SecureRandom();

    @Transactional
    public OAuth2LoginResponse processOAuth2Login(OAuth2User oauth2User, HttpServletResponse response, HttpServletRequest request) {

        // Null Guard: Check email and sub (googleId) from OAuth2 attributes
        if (oauth2User == null) {
            log.error("OAuth2User is null");
            throw new BadRequestException("OAuth2 authentication failed");
        }

        String email = oauth2User.getAttribute("email");
        String googleId = oauth2User.getAttribute("sub");

        if (email == null || email.isBlank() || googleId == null || googleId.isBlank()) {
            log.error("Missing required OAuth2 attributes. Email: {}, GoogleId: {}", email, googleId);
            throw new BadRequestException("Invalid Google OAuth response - missing required information");
        }

        String name = oauth2User.getAttribute("name");

        AuthUserCredentials user = userRepository.findByEmail(email).orElse(null);
        boolean isNewUser = false;

        if (user != null) {
            // Account Linking: Link googleId, set isEmailVerified=true, update updatedAt & lastLoginAt, save user
            user.setGoogleId(googleId);
            user.setEmailVerified(true);
            user.setUpdatedAt(LocalDateTime.now());
            user.setLastLoginAt(LocalDateTime.now());
            user = userRepository.save(user);
        } else {
            // Auto-Provisioning for new user with concurrency protection
            try {
                user = createNewOAuthUser(email, name, googleId);
                isNewUser = true;
            } catch (DataIntegrityViolationException e) {
                log.warn("Concurrent registration detected for email: {}. Falling back to fetch existing user.", email);
                user = userRepository.findByEmail(email)
                        .orElseThrow(() -> new BadRequestException("Failed to complete OAuth registration"));
            }
        }

        // Validate user status
        validateUserStatus(user);

        // Generate unified sessionId
        UUID sessionId = UUID.randomUUID();

        // Generate tokens
        String accessToken = jwtService.generateAccessToken(user);
        String refreshToken = jwtService.generateRefreshToken(user);

        // Save tokens in database using unified sessionId
        tokenService.saveAccessToken(user.getAuthUserId(), accessToken, sessionId);
        tokenService.saveRefreshToken(user.getAuthUserId(), refreshToken, sessionId);

        // Force flush
        entityManager.flush();

        // Set HttpOnly cookies
        cookiesService.setAccessTokenCookie(response, accessToken);
        cookiesService.setRefreshTokenCookie(response, refreshToken);

        // Log security event
        securityEvents.logSecurityEvent(
                user,
                "OAUTH2_LOGIN",
                "User logged in via Google OAuth2",
                request
        );

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
        String usernameId = generateUniqueUsernameId();
        String username = sanitizeUsername(name, email);
        String dummyPasswordHash = "$2a$10$OAUTH2_NO_LOCAL_PASSWORD_PLACEHOLDER";

        AuthUserCredentials newUser = AuthUserCredentials.builder()
                // DO NOT pre-assign authUserId; allow JPA @GeneratedValue to generate UUID for INSERT
                .usernameId(usernameId)
                .username(username)
                .email(email)
                .googleId(googleId)
                .isEmailVerified(true)
                .isPhoneVerified(false)
                .mfaEnabled(false)
                .status(AuthUserCredentials.Status.ACTIVE)
                .loginType(AuthUserCredentials.LoginType.THIRD_PARTY)
                .role(Role.USER)
                .passwordHash(dummyPasswordHash)
                .createdAt(LocalDateTime.now())
                .updatedAt(LocalDateTime.now())
                .lastLoginAt(LocalDateTime.now())
                .build();

        AuthUserCredentials savedUser = userRepository.save(newUser);
        try {
            authEventPublisher.publishUserRegistered(savedUser);
        } catch (Exception e) {
            log.error("Failed to publish user registered event for OAuth2 user: {}", savedUser.getAuthUserId(), e);
        }
        return savedUser;
    }

    private String sanitizeUsername(String name, String email) {
        String username = name;
        if (username == null || username.isBlank()) {
            if (email != null && email.contains("@")) {
                username = email.substring(0, email.indexOf("@"));
            } else {
                username = "User";
            }
        }
        username = username.trim();
        if (username.length() > 20) {
            username = username.substring(0, 20);
        }
        if (username.isBlank()) {
            username = "User";
        }
        return username;
    }

    private String generateUniqueUsernameId() {
        String chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        String usernameId;
        int attempts = 0;
        do {
            StringBuilder sb = new StringBuilder("MS_");
            for (int i = 0; i < 8; i++) {
                sb.append(chars.charAt(random.nextInt(chars.length())));
            }
            usernameId = sb.toString();
            attempts++;
            if (attempts >= 10) {
                usernameId = "MS_" + generateRandomString(4) + (System.currentTimeMillis() % 10000);
                break;
            }
        } while (userRepository.existsByUsernameId(usernameId));

        return usernameId;
    }

    private String generateRandomString(int length) {
        String chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        StringBuilder sb = new StringBuilder(length);
        for (int i = 0; i < length; i++) {
            sb.append(chars.charAt(random.nextInt(chars.length())));
        }
        return sb.toString();
    }

    private void validateUserStatus(AuthUserCredentials user) {
        if (user.getStatus() == AuthUserCredentials.Status.SUSPENDED) {
            throw new ForbiddenException("Account is suspended");
        }
        if (user.getStatus() == AuthUserCredentials.Status.LOCKED) {
            throw new ForbiddenException("Account is locked");
        }
    }
}
