package com.rolesync.authservice.controllers;

import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.KeyUse;
import com.nimbusds.jose.jwk.RSAKey;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.security.KeyPair;
import java.security.interfaces.RSAPublicKey;
import java.util.Map;

/**
 * Publishes the RS256 public key as a JWK Set so other services (notably the
 * API gateway) can verify access-token signatures without sharing the private
 * key or copying a static PEM. Fetching JWKS keeps verifiers in sync when the
 * key pair is (re)generated.
 *
 * <p>Exposed under {@code /api/v1/auth/oauth2/**}, which auth-service's
 * SecurityConfig already treats as a public endpoint. Only the PUBLIC key is
 * ever serialized here.
 */
@RestController
@RequestMapping("/api/v1/auth/oauth2")
@RequiredArgsConstructor
public class JwksController {

    private final KeyPair keyPair;

    @GetMapping(value = "/jwks", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> jwks() {
        RSAPublicKey publicKey = (RSAPublicKey) keyPair.getPublic();

        RSAKey jwk = new RSAKey.Builder(publicKey)
                .keyUse(KeyUse.SIGNATURE)
                .algorithm(JWSAlgorithm.RS256)
                .build();

        // toJSONObject() emits public parameters only.
        return new JWKSet(jwk).toJSONObject();
    }
}
