package com.rolesync.gatewayservice.security;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.proc.JWSVerificationKeySelector;
import com.nimbusds.jose.proc.SecurityContext;
import com.nimbusds.jose.jwk.source.JWKSource;
import com.nimbusds.jose.jwk.source.JWKSourceBuilder;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.proc.ConfigurableJWTProcessor;
import com.nimbusds.jwt.proc.DefaultJWTClaimsVerifier;
import com.nimbusds.jwt.proc.DefaultJWTProcessor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import jakarta.annotation.PostConstruct;
import java.net.URI;
import java.net.URL;
import java.util.Set;

/**
 * Verifies RoleSync access tokens (RS256) against the auth-service JWKS.
 *
 * <p>Checks: RS256 signature, expiry ({@code exp}), issuer ({@code iss}), and
 * presence of the {@code userId} claim. Token-type ({@code ACCESS} vs
 * {@code REFRESH}) is checked by the caller. Revocation is intentionally NOT
 * checked here — that state lives in auth-service; the gateway only proves the
 * token is authentic and unexpired.
 *
 * <p>Nimbus performs blocking JWKS fetches on cache miss, so verification runs
 * on the bounded-elastic scheduler rather than the Netty event loop. The JWK
 * set is cached and refreshed ahead of expiry by {@link JWKSourceBuilder}
 * defaults.
 */
@Component
public class JwtVerifier {

    private static final Logger log = LoggerFactory.getLogger(JwtVerifier.class);

    private final String jwksUri;
    private final String issuer;

    private ConfigurableJWTProcessor<SecurityContext> jwtProcessor;

    public JwtVerifier(
            @Value("${gateway.security.jwks-uri:http://auth-service:8082/api/v1/auth/oauth2/jwks}") String jwksUri,
            @Value("${gateway.security.issuer:rolesync-micro-authservice}") String issuer) {
        this.jwksUri = jwksUri;
        this.issuer = issuer;
    }

    @PostConstruct
    void init() throws Exception {
        URL jwksUrl = URI.create(jwksUri).toURL();

        // Caching JWK source: fetched lazily on first use, then cached and
        // refreshed ahead of expiry. No network call happens at startup.
        JWKSource<SecurityContext> jwkSource = JWKSourceBuilder.create(jwksUrl).build();

        DefaultJWTProcessor<SecurityContext> processor = new DefaultJWTProcessor<>();
        processor.setJWSKeySelector(new JWSVerificationKeySelector<>(JWSAlgorithm.RS256, jwkSource));

        // Requires exact issuer match and presence of exp + userId. exp/nbf are
        // validated automatically by DefaultJWTClaimsVerifier (60s clock skew).
        processor.setJWTClaimsSetVerifier(new DefaultJWTClaimsVerifier<>(
                new JWTClaimsSet.Builder().issuer(issuer).build(),
                Set.of("exp", "userId")));

        this.jwtProcessor = processor;
        log.info("JwtVerifier initialized (jwksUri={}, issuer={})", jwksUri, issuer);
    }

    /**
     * Verifies the token and returns its claims, or errors if the token is
     * malformed, unsigned by a known key, expired, or from the wrong issuer.
     */
    public Mono<JWTClaimsSet> verify(String token) {
        return Mono.fromCallable(() -> jwtProcessor.process(token, null))
                .subscribeOn(Schedulers.boundedElastic());
    }
}
