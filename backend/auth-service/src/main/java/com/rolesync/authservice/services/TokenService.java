package com.rolesync.authservice.services;

import com.rolesync.authservice.models.AuthUserCredentials;
import com.rolesync.authservice.models.TokenStore;
import com.rolesync.authservice.repository.TokenStoreRepository;
import com.rolesync.authservice.repository.UserRepository;
import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.Optional;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class TokenService {

    private final TokenStoreRepository tokenStoreRepository;
    private final UserRepository userRepository;
    private final JwtService jwtService;
    private final EntityManager entityManager;

    /**
     * Save access token using saveToken to the database
     */
    @Transactional
    public void saveAccessToken(UUID userId, String accessToken) {
        saveAccessToken(userId, accessToken, UUID.randomUUID());
    }

    @Transactional
    public void saveAccessToken(UUID userId, String accessToken, UUID sessionId) {
        saveToken(userId, accessToken, "ACCESS", sessionId);
    }

    /**
     * Save RefreshToken using saveToken to the database
     */
    @Transactional
    public void saveRefreshToken(UUID userId, String refreshToken) {
        saveRefreshToken(userId, refreshToken, UUID.randomUUID());
    }

    @Transactional
    public void saveRefreshToken(UUID userId, String refreshToken, UUID sessionId) {
        saveToken(userId, refreshToken, "REFRESH", sessionId);
    }

    /**
     * Save token functions to store tokens in the database
     */
    private void saveToken(UUID userId, String token, String tokenType, UUID sessionId) {

        AuthUserCredentials user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("User not found with ID: " + userId));

        Jwt jwt = jwtService.validateAndDecodeToken(token);

        TokenStore tokenStore = TokenStore.builder()
                .authUser(user)
                .tokenString(token)
                .tokenType(tokenType)
                .sessionId(sessionId)
                .issuedAt(convertToLocalDateTime(jwt.getIssuedAt()))
                .expiresAt(convertToLocalDateTime(jwt.getExpiresAt()))
                .deviceFingerprint("Win")
                .revoked(false)
                .build();

        tokenStoreRepository.save(tokenStore);
        entityManager.flush();

        log.info("{} token saved with session ID {} for user ID: {}", tokenType, sessionId, userId);
    }

    /**
     * Scheduled cleanup task for expired or revoked tokens.
     * Runs daily at 2:00 AM.
     */
    @Scheduled(cron = "0 0 2 * * *")
    @Transactional
    public void cleanupExpiredTokens() {
        try {
            LocalDateTime now = LocalDateTime.now();
            int deleted = tokenStoreRepository.deleteExpiredOrRevoked(now);
            log.info("Cleanup completed: Pruned {} expired or revoked tokens from TokenStore", deleted);
        } catch (Exception e) {
            log.error("Error during scheduled cleanup of TokenStore: {}", e.getMessage(), e);
        }
    }

    /**
     * Check Token Validity
     * 
     * @param token String
     */
    @Transactional(readOnly = true)
    public boolean isTokenValid(String token) {
        try {

            Optional<TokenStore> tokenStore = tokenStoreRepository
                    .findByTokenStringAndRevokedFalse(token);

            return tokenStore.isPresent() && !jwtService.isTokenExpired(token);
        } catch (Exception e) {
            log.error("Token validation failed: {}", e.getMessage());
            return false;
        }
    }

    /**
     * Check if token is revoked
     * 
     * @param token String
     * @return boolean
     */
    @Transactional(readOnly = true)
    public boolean isTokenRevoked(String token) {
        Optional<TokenStore> tokenStore = tokenStoreRepository.findByTokenStringAndRevokedFalse(token);
        return tokenStore.isEmpty();
    }

    /**
     * Revoke Token
     * 
     * @param token String
     */
    @Transactional
    public void revokeToken(String token) {
        tokenStoreRepository.findByTokenStringAndRevokedFalse(token)
                .ifPresent(tokenStore -> {
                    tokenStore.setRevoked(true);
                    tokenStoreRepository.save(tokenStore);
                    log.info("Token revoked for user ID: {}", tokenStore.getAuthUser().getAuthUserId());
                });
    }

    /**
     * Revoke all user tokens
     * 
     * @param userId UUID
     */
    @Transactional
    public void revokeAllUserTokens(UUID userId) {
        int updated = tokenStoreRepository.revokeAllByUserId(userId);
        log.info("All tokens revoked for user ID: {} (count: {})", userId, updated);
    }

    /**
     * Revoke all user tokens by type
     * 
     * @param tokenType String
     */
    @Transactional
    public void revokeAllUserTokensByType(UUID userId, String tokenType) {
        int updated = tokenStoreRepository.revokeAllByUserIdAndType(userId, tokenType);
        log.info("All {} tokens revoked for user ID: {} (count: {})", tokenType, userId, updated);
    }

    /**
     * Convert Instant to LocalDateTime
     * 
     * @param instant java.time.Instant
     */
    private LocalDateTime convertToLocalDateTime(java.time.Instant instant) {
        return instant != null
                ? LocalDateTime.ofInstant(instant, ZoneId.systemDefault())
                : null;
    }

}
