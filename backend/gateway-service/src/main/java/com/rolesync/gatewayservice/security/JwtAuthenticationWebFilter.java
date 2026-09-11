package com.rolesync.gatewayservice.security;

import com.nimbusds.jwt.JWTClaimsSet;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpCookie;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilter;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;

/**
 * Edge authentication for the API gateway.
 *
 * <p>The gateway is the trust boundary: it verifies the {@code access_token}
 * RS256 cookie, then hands downstream services a TRUSTED identity via
 * {@code X-User-Id} / {@code X-Auth-User-Id} (and {@code X-User-Email}).
 * Client-supplied copies of those headers are always stripped first, so a
 * caller can never forge their identity through the gateway.
 *
 * <p>Scope of this control:
 * <ul>
 *   <li>Public prefixes (auth endpoints, Composio webhooks) pass through
 *       without a token — auth-service self-authenticates its protected
 *       routes, and webhooks authenticate by signature.</li>
 *   <li>Everything else requires a valid, unexpired, correctly-issued ACCESS
 *       token or gets a 401.</li>
 *   <li>Identity ({@code who}) is now trusted. Tenant authorization
 *       ({@code X-Tenant-Id} = which workspace) is NOT asserted here — the JWT
 *       carries no tenant claim, so downstream services must still verify the
 *       user is a member of the tenant they act on.</li>
 * </ul>
 *
 * <p>NOTE: this only protects traffic that actually transits the gateway.
 * Publishing service ports directly (docker-compose) bypasses it — services
 * should not be reachable off the internal network, or should additionally
 * verify the cookie themselves.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 100)
public class JwtAuthenticationWebFilter implements WebFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationWebFilter.class);

    private static final String ACCESS_TOKEN_COOKIE = "access_token";
    private static final String HDR_USER_ID = "X-User-Id";
    private static final String HDR_AUTH_USER_ID = "X-Auth-User-Id";
    private static final String HDR_USER_EMAIL = "X-User-Email";

    /** Client-controlled identity headers that must never be trusted inbound. */
    private static final List<String> SPOOFABLE_IDENTITY_HEADERS =
            List.of(HDR_USER_ID, HDR_AUTH_USER_ID, HDR_USER_EMAIL);

    private final JwtVerifier jwtVerifier;
    private final List<String> publicPathPrefixes;

    public JwtAuthenticationWebFilter(
            JwtVerifier jwtVerifier,
            @Value("${gateway.security.public-paths:/api/v1/auth/,/api/v1/webhooks/}") String publicPaths) {
        this.jwtVerifier = jwtVerifier;
        this.publicPathPrefixes = Arrays.stream(publicPaths.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, WebFilterChain chain) {
        ServerHttpRequest request = exchange.getRequest();
        String path = request.getPath().value();

        // CORS preflight: never authenticate; let the CORS filter answer it.
        if (request.getMethod() == HttpMethod.OPTIONS) {
            return chain.filter(stripIdentityHeaders(exchange));
        }

        // Public routes: no token required, but still strip forged identity.
        if (isPublicPath(path)) {
            return chain.filter(stripIdentityHeaders(exchange));
        }

        String token = extractAccessToken(request);
        if (token == null || token.isBlank()) {
            return unauthorized(exchange, "Authentication required");
        }

        return jwtVerifier.verify(token)
                .map(Optional::of)
                .onErrorResume(ex -> {
                    log.debug("Access token verification failed for {}: {}", path, ex.getMessage());
                    return Mono.just(Optional.empty());
                })
                .defaultIfEmpty(Optional.empty())
                .flatMap(verified -> {
                    if (verified.isEmpty()) {
                        return unauthorized(exchange, "Invalid or expired token");
                    }
                    JWTClaimsSet claims = verified.get();
                    String userId = claimAsString(claims, "userId");
                    String tokenType = claimAsString(claims, "tokenType");

                    if (userId == null || userId.isBlank() || !"ACCESS".equals(tokenType)) {
                        return unauthorized(exchange, "Invalid access token");
                    }

                    String email = claimAsString(claims, "email");
                    // Only token problems become 401s. Errors from routing or the downstream
                    // service (e.g. no instance available during a restart) pass through as
                    // themselves: clients treat a 401 as a lost session and sign the user out.
                    return chain.filter(withTrustedIdentity(exchange, userId, email));
                });
    }

    private boolean isPublicPath(String path) {
        for (String prefix : publicPathPrefixes) {
            if (path.startsWith(prefix)) {
                return true;
            }
        }
        return false;
    }

    private String extractAccessToken(ServerHttpRequest request) {
        HttpCookie cookie = request.getCookies().getFirst(ACCESS_TOKEN_COOKIE);
        return cookie != null ? cookie.getValue() : null;
    }

    /** Removes any inbound identity headers so clients cannot forge them. */
    private ServerWebExchange stripIdentityHeaders(ServerWebExchange exchange) {
        ServerHttpRequest mutated = exchange.getRequest().mutate()
                .headers(headers -> SPOOFABLE_IDENTITY_HEADERS.forEach(headers::remove))
                .build();
        return exchange.mutate().request(mutated).build();
    }

    /** Strips forged identity headers, then sets the gateway-verified identity. */
    private ServerWebExchange withTrustedIdentity(ServerWebExchange exchange, String userId, String email) {
        ServerHttpRequest mutated = exchange.getRequest().mutate()
                .headers(headers -> {
                    SPOOFABLE_IDENTITY_HEADERS.forEach(headers::remove);
                    headers.set(HDR_USER_ID, userId);
                    headers.set(HDR_AUTH_USER_ID, userId);
                    if (email != null && !email.isBlank()) {
                        headers.set(HDR_USER_EMAIL, email);
                    }
                })
                .build();
        return exchange.mutate().request(mutated).build();
    }

    private String claimAsString(JWTClaimsSet claims, String name) {
        Object value = claims.getClaim(name);
        return value != null ? value.toString() : null;
    }

    private Mono<Void> unauthorized(ServerWebExchange exchange, String message) {
        ServerHttpResponse response = exchange.getResponse();
        response.setStatusCode(HttpStatus.UNAUTHORIZED);
        response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
        String body = "{\"message\":\"" + message + "\",\"status\":401}";
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        return response.writeWith(Mono.just(response.bufferFactory().wrap(bytes)));
    }
}
