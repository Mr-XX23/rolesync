package com.medisecure.authservice.configurations;

import com.medisecure.authservice.services.JwtService;
import com.medisecure.authservice.services.TokenService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfTokenRequestAttributeHandler;

import jakarta.annotation.PostConstruct;

@Configuration
@EnableWebSecurity
@EnableMethodSecurity(prePostEnabled = true) // Enable @PreAuthorize
@RequiredArgsConstructor
@ConditionalOnProperty(value = "security.enabled", havingValue = "true", matchIfMissing = true)
@Slf4j
public class SecurityConfig {

        private final JwtService jwtService;
        private final TokenService tokenService;
        private final JwtDecoder jwtDecoder;
        private final PublicEndpointsConfig publicEndpointsConfig;
        private final OAuth2AuthenticationSuccessHandler oauth2SuccessHandler;

        @Value("${security.csrf.enabled:false}")
        private boolean csrfEnabled;

        @Value("${spring.profiles.active:dev}")
        private String activeProfile;

        @PostConstruct
        public void logSecurityConfig() {
                log.info("Security Configuration Initialized:");
                log.info("  CSRF Protection: {}", csrfEnabled ? "ENABLED" : "DISABLED");
                log.info("  Session Management: STATELESS (JWT)");
                log.info("  Active Profile: {}", activeProfile);

                if (!csrfEnabled) {
                        log.warn("⚠️ CSRF Protection is DISABLED");
                        log.warn("⚠️ Current CSRF mitigation:");
                        log.warn("   - SameSite=Strict cookies (prevents CSRF via cookies)");
                        log.warn("   - CORS policy restricts cross-origin requests");
                        log.warn("   - Stateless JWT (no session cookies)");
                        log.warn("⚠️ Enable CSRF for additional defense-in-depth: security.csrf.enabled=true");
                } else {
                        log.info("✓ CSRF Protection ENABLED with cookie-based tokens");
                }
        }

        /**
         * Configure security filter chain
         * SECURITY: Configurable CSRF protection with cookie-based tokens
         * 
         * @param http HttpSecurity
         */
        @Bean
        public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
                // CSRF Configuration
                if (csrfEnabled) {
                        // SECURITY FIX: Enable CSRF with cookie-based token repository
                        CookieCsrfTokenRepository tokenRepository = CookieCsrfTokenRepository.withHttpOnlyFalse();
                        tokenRepository.setCookieName("XSRF-TOKEN");
                        tokenRepository.setHeaderName("X-XSRF-TOKEN");

                        CsrfTokenRequestAttributeHandler requestHandler = new CsrfTokenRequestAttributeHandler();
                        requestHandler.setCsrfRequestAttributeName("_csrf");

                        http.csrf(csrf -> csrf
                                        .csrfTokenRepository(tokenRepository)
                                        .csrfTokenRequestHandler(requestHandler)
                                        // Ignore CSRF for API endpoints using JWT bearer tokens (not vulnerable to
                                        // CSRF)
                                        .ignoringRequestMatchers("/api/v1/auth/login", "/api/v1/auth/register",
                                                        "/api/v1/auth/health/**"));

                        log.info("CSRF protection configured with cookie-based tokens");
                } else {
                        // CSRF disabled - relies on SameSite cookies and CORS for protection
                        http.csrf(csrf -> csrf.disable());
                }

                http
                                .sessionManagement(session -> session
                                                .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                                .authorizeHttpRequests(auth -> auth
                                                .requestMatchers(publicEndpointsConfig.getPublicEndpoints()).permitAll()
                                                .anyRequest().authenticated())
                                .oauth2Login(oauth2 -> oauth2
                                                .loginPage("/oauth2/authorization/google")
                                                .defaultSuccessUrl("/api/v1/auth/oauth2/callback/google", true)
                                                .successHandler(oauth2SuccessHandler)
                                                .failureUrl("/login?error=oauth_failed"))
                                .oauth2ResourceServer(oauth2 -> oauth2.jwt(jwt -> jwt.decoder(jwtDecoder)))
                                .addFilterBefore(
                                                new JwtAuthenticationFilter(jwtService, tokenService,
                                                                publicEndpointsConfig.getPublicEndpoints()),
                                                UsernamePasswordAuthenticationFilter.class);

                return http.build();
        }
}
