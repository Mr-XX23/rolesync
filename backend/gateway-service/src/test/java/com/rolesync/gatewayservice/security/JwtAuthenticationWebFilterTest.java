package com.rolesync.gatewayservice.security;

import com.nimbusds.jwt.JWTClaimsSet;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpCookie;
import org.springframework.http.HttpStatus;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;
import org.springframework.web.server.WebFilterChain;
import reactor.core.publisher.Mono;
import reactor.test.StepVerifier;

import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Offline unit tests for the edge auth filter — no Spring context, no network.
 * Verifies the security contract: token required on protected routes, forged
 * identity headers stripped, and gateway-verified identity injected downstream.
 */
class JwtAuthenticationWebFilterTest {

    private static final String PUBLIC_PATHS = "/api/v1/auth/,/api/v1/webhooks/";

    /**
     * Hand-rolled stub — Mockito's inline mock maker can't self-attach on JDK 25.
     * {@code super(...)} only stores fields; the JWKS wiring lives in the
     * {@code @PostConstruct}, which {@code new} does not invoke, so no network.
     */
    private static class StubVerifier extends JwtVerifier {
        private final Mono<JWTClaimsSet> result;

        StubVerifier(Mono<JWTClaimsSet> result) {
            super("http://localhost/jwks", "test-issuer");
            this.result = result;
        }

        @Override
        public Mono<JWTClaimsSet> verify(String token) {
            return result;
        }
    }

    private JwtAuthenticationWebFilter filterReturning(Mono<JWTClaimsSet> verifyResult) {
        return new JwtAuthenticationWebFilter(new StubVerifier(verifyResult), PUBLIC_PATHS);
    }

    private static JWTClaimsSet accessClaims(String userId, String email) {
        return new JWTClaimsSet.Builder()
                .claim("userId", userId)
                .claim("tokenType", "ACCESS")
                .claim("email", email)
                .build();
    }

    @Test
    void protectedRouteWithoutTokenReturns401() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/workspaces/profile"));

        StepVerifier.create(filterReturning(Mono.empty()).filter(exchange, e -> Mono.empty()))
                .verifyComplete();

        assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
    }

    @Test
    void publicRoutePassesThroughButStripsForgedIdentity() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/auth/login")
                        .header("X-User-Id", "spoofed"));

        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
        WebFilterChain chain = e -> {
            forwarded.set(e);
            return Mono.empty();
        };

        StepVerifier.create(filterReturning(Mono.empty()).filter(exchange, chain)).verifyComplete();

        assertNull(exchange.getResponse().getStatusCode());
        assertNull(forwarded.get().getRequest().getHeaders().getFirst("X-User-Id"),
                "client-supplied X-User-Id must be stripped even on public routes");
    }

    @Test
    void validAccessTokenInjectsVerifiedIdentityAndStripsSpoof() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/workspaces/profile")
                        .header("X-User-Id", "attacker-uuid")
                        .cookie(new HttpCookie("access_token", "good-token")));

        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();
        WebFilterChain chain = e -> {
            forwarded.set(e);
            return Mono.empty();
        };

        var filter = filterReturning(Mono.just(accessClaims("real-user-uuid", "user@example.com")));
        StepVerifier.create(filter.filter(exchange, chain)).verifyComplete();

        var headers = forwarded.get().getRequest().getHeaders();
        assertEquals("real-user-uuid", headers.getFirst("X-User-Id"));
        assertEquals("real-user-uuid", headers.getFirst("X-Auth-User-Id"));
        assertEquals("user@example.com", headers.getFirst("X-User-Email"));
    }

    @Test
    void refreshTokenIsRejectedOnProtectedRoute() {
        JWTClaimsSet refresh = new JWTClaimsSet.Builder()
                .claim("userId", "real-user-uuid")
                .claim("tokenType", "REFRESH")
                .build();

        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/catalog/products")
                        .cookie(new HttpCookie("access_token", "refresh-token")));

        StepVerifier.create(filterReturning(Mono.just(refresh)).filter(exchange, e -> Mono.empty()))
                .verifyComplete();

        assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
    }

    @Test
    void invalidTokenReturns401() {
        MockServerWebExchange exchange = MockServerWebExchange.from(
                MockServerHttpRequest.get("/api/v1/knowledge-vault/documents")
                        .cookie(new HttpCookie("access_token", "bad-token")));

        var filter = filterReturning(Mono.error(new RuntimeException("bad signature")));
        StepVerifier.create(filter.filter(exchange, e -> Mono.empty())).verifyComplete();

        assertEquals(HttpStatus.UNAUTHORIZED, exchange.getResponse().getStatusCode());
    }
}
