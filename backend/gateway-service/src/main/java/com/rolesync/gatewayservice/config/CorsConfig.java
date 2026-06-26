package com.medisecure.gatewayservice.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.reactive.CorsWebFilter;
import org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource;

import jakarta.annotation.PostConstruct;
import java.util.Arrays;
import java.util.List;

/**
 * CORS Configuration for Gateway Service
 * SECURITY: Externalized configuration with environment-specific settings
 */
@Configuration
public class CorsConfig {

    private static final Logger log = LoggerFactory.getLogger(CorsConfig.class);

    @Value("${cors.allowed-origins:http://localhost:5173,http://localhost:8080}")
    private String allowedOrigins;

    @Value("${cors.allowed-methods:GET,POST,PUT,DELETE,OPTIONS,PATCH}")
    private String allowedMethods;

    @Value("${cors.allowed-headers:Authorization,Content-Type,X-Requested-With,Accept,Origin}")
    private String allowedHeaders;

    @Value("${cors.allow-credentials:true}")
    private boolean allowCredentials;

    @Value("${cors.max-age:600}")
    private long maxAge;

    @Value("${spring.profiles.active:dev}")
    private String activeProfile;

    @PostConstruct
    public void logCorsConfiguration() {
        log.info("CORS Configuration Initialized:");
        log.info("  Allowed Origins: {}", allowedOrigins);
        log.info("  Allowed Methods: {}", allowedMethods);
        log.info("  Allowed Headers: {}", allowedHeaders);
        log.info("  Allow Credentials: {}", allowCredentials);
        log.info("  Max Age: {} seconds", maxAge);
        log.info("  Active Profile: {}", activeProfile);

        // Security warning for production
        if (("prod".equalsIgnoreCase(activeProfile) || "production".equalsIgnoreCase(activeProfile))
                && allowedOrigins.contains("localhost")) {
            log.warn("⚠️ SECURITY WARNING: Production environment detected with localhost in allowed origins!");
            log.warn("⚠️ Update cors.allowed-origins in production configuration!");
        }
    }

    @Bean
    public CorsWebFilter corsWebFilter() {
        CorsConfiguration corsConfig = new CorsConfiguration();

        // SECURITY FIX: Use externalized configuration instead of hardcoded values
        corsConfig.setAllowedOrigins(parseCommaSeparated(allowedOrigins));
        corsConfig.setAllowedMethods(parseCommaSeparated(allowedMethods));

        // SECURITY FIX: Whitelist specific headers instead of wildcard
        corsConfig.setAllowedHeaders(parseCommaSeparated(allowedHeaders));

        corsConfig.setAllowCredentials(allowCredentials);
        corsConfig.setMaxAge(maxAge);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", corsConfig);

        log.info("✓ CORS Web Filter configured successfully");
        return new CorsWebFilter(source);
    }

    /**
     * Parse comma-separated configuration values
     */
    private List<String> parseCommaSeparated(String value) {
        return Arrays.stream(value.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }
}
