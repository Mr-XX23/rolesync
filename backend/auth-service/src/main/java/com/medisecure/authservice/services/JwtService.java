package com.medisecure.authservice.services;

import com.medisecure.authservice.exceptions.UnauthorizedException;
import com.medisecure.authservice.models.AuthUserCredentials;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.temporal.ChronoUnit;

@Service
@RequiredArgsConstructor
@Slf4j
public class JwtService {


    private final JwtEncoder jwtEncoder;
    private final JwtDecoder jwtDecoder;

    @Value("${jwt.access-token-expiry-days:7}")
    private Long accessTokenExpiryDays;

    @Value("${jwt.refresh-token-expiry-days:30}")
    private Long refreshTokenExpiryDays;

    @Value("${jwt.issuer:medisecure-auth-service}")
    private String issuer;

    /**
     * Get the accessToken in string
     * @param  user AuthUserCredentials
     */
    public String generateAccessToken(AuthUserCredentials user) {

        try {

            // Get current time
            Instant now = Instant.now();

            // Calculate expiry time ( add accessTokenExpiryDays to current time )
            Instant expiry = now.plus(accessTokenExpiryDays, ChronoUnit.DAYS);

            // Build JWT claims
            JwtClaimsSet claims = JwtClaimsSet.builder()
                    .issuer(issuer)
                    .issuedAt(now)
                    .expiresAt(expiry)
                    .subject(user.getUsername())
                    .claim("userId", user.getAuthUserId().toString())
                    .claim("email", user.getEmail())
                    .claim("tokenType", "ACCESS")
                    .claim("scope", "read write")
                    .build();


            String token = jwtEncoder.encode(JwtEncoderParameters.from(claims)).getTokenValue();
            log.info("Generated access token for user: {}", user.getUsername());
            return token;

        } catch (Exception e) {
            log.error("Error generating access token for user: {}", user.getUsername(), e);
            throw new RuntimeException("Failed to generate access token", e);
        }
    }

    /**
     * Get the refreshToken in string
     * @param  user AuthUserCredentials
     */
    public String generateRefreshToken(AuthUserCredentials user) {
        try {
            Instant now = Instant.now();
            Instant expiry = now.plus(refreshTokenExpiryDays, ChronoUnit.DAYS);

            JwtClaimsSet claims = JwtClaimsSet.builder()
                    .issuer(issuer)
                    .issuedAt(now)
                    .expiresAt(expiry)
                    .subject(user.getUsername())
                    .claim("userId", user.getAuthUserId().toString())
                    .claim("tokenType", "REFRESH")
                    .claim("scope", "refresh")
                    .build();

            String token = jwtEncoder.encode(JwtEncoderParameters.from(claims)).getTokenValue();
            log.info("Generated refresh token for user: {}", user.getUsername());
            return token;
        } catch (Exception e) {
            log.error("Error generating refresh token for user: {}", user.getUsername(), e);
            throw new RuntimeException("Failed to generate refresh token", e);
        }
    }

    /**
     * Validate Token in string
     * @param  token String
     */
    public Jwt validateAndDecodeToken(String token) {
        try {
            return jwtDecoder.decode(token);
        } catch (JwtException e) {
            log.error("Invalid JWT token: {}", e.getMessage());
            throw new UnauthorizedException("Invalid or expired JWT token");
        }
    }

    /**
     * Extract UserId from Token
     * @param  token String
     */
    public String extractUserId(String token) {
        Jwt jwt = validateAndDecodeToken(token);
        return jwt.getClaim("userId");
    }

    /**
     * Check if Token is expired
     * @param  token String
     */
    public boolean isTokenExpired(String token) {
        try {
            Jwt jwt = validateAndDecodeToken(token);
            return jwt.getExpiresAt() != null && jwt.getExpiresAt().isBefore(Instant.now());
        } catch (JwtException e) {
            return true;
        }
    }

}
