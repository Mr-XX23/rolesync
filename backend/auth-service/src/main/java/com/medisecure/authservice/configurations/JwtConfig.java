package com.medisecure.authservice.configurations;

import com.nimbusds.jose.jwk.JWK;
import com.nimbusds.jose.jwk.JWKSet;
import com.nimbusds.jose.jwk.RSAKey;
import com.nimbusds.jose.jwk.source.ImmutableJWKSet;
import com.nimbusds.jose.jwk.source.JWKSource;
import com.nimbusds.jose.proc.SecurityContext;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.Resource;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;

@Configuration
@Slf4j
public class JwtConfig {

    @Value("${jwt.public-key:#{null}}")
    private Resource publicKeyResource;

    @Value("${jwt.private-key:#{null}}")
    private Resource privateKeyResource;

    @Value("${spring.profiles.active:dev}")
    private String activeProfile;

    /**
     * Generate RSA Key Pair with persistence support
     * SECURITY FIX: Persist keys to prevent token invalidation on restart
     */
    @Bean
    public KeyPair keyPair() {
        try {
            // Try to load existing keys
            if (publicKeyResource != null && privateKeyResource != null &&
                    publicKeyResource.exists() && privateKeyResource.exists()) {

                log.info("Loading existing RSA key pair from: {} and {}",
                        publicKeyResource.getFilename(), privateKeyResource.getFilename());

                RSAPublicKey publicKey = readPublicKey(publicKeyResource);
                RSAPrivateKey privateKey = readPrivateKey(privateKeyResource);

                log.info("✓ Successfully loaded RSA key pair from files");
                return new KeyPair(publicKey, privateKey);
            }

            // PRODUCTION CHECK: Fail fast if keys are missing in production
            if ("prod".equalsIgnoreCase(activeProfile) || "production".equalsIgnoreCase(activeProfile)) {
                throw new IllegalStateException(
                        "CRITICAL SECURITY ERROR: JWT keys not found in production! " +
                                "Keys must be pre-generated and configured. " +
                                "Generate keys using: ./auth-service/scripts/generate-jwt-keys.sh");
            }

            // Development: Generate and persist new keys
            log.warn("⚠️ JWT keys not found. Generating new RSA key pair for development...");
            log.warn("⚠️ This will invalidate all existing tokens!");

            KeyPair newKeyPair = generateNewKeyPair();
            persistKeyPair(newKeyPair);

            log.info("✓ New RSA key pair generated and persisted to src/main/resources/keys/");
            return newKeyPair;

        } catch (Exception e) {
            log.error("Failed to load or generate RSA key pair", e);
            throw new IllegalStateException("Unable to configure RSA key pair for JWT", e);
        }
    }

    /**
     * Generate a new RSA key pair
     */
    private KeyPair generateNewKeyPair() throws Exception {
        KeyPairGenerator keyPairGenerator = KeyPairGenerator.getInstance("RSA");
        keyPairGenerator.initialize(2048);
        return keyPairGenerator.generateKeyPair();
    }

    /**
     * Persist key pair to filesystem for reuse across restarts
     * Creates keys/ directory in src/main/resources/
     */
    private void persistKeyPair(KeyPair keyPair) {
        try {
            // Create keys directory if it doesn't exist
            String resourcesPath = "src/main/resources/keys";
            Files.createDirectories(Paths.get(resourcesPath));

            // Write public key
            String publicKeyPath = resourcesPath + "/public_key.pem";
            writeKeyToFile(keyPair.getPublic().getEncoded(), publicKeyPath,
                    "-----BEGIN PUBLIC KEY-----", "-----END PUBLIC KEY-----");
            log.info("Public key saved to: {}", publicKeyPath);

            // Write private key
            String privateKeyPath = resourcesPath + "/private_key_pkcs8.pem";
            writeKeyToFile(keyPair.getPrivate().getEncoded(), privateKeyPath,
                    "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----");
            log.info("Private key saved to: {}", privateKeyPath);

            log.warn("⚠️ IMPORTANT: Add keys/ directory to .gitignore to prevent committing private keys!");

        } catch (Exception e) {
            log.error("Failed to persist key pair - keys will be regenerated on next restart", e);
            // Don't fail - just warn
        }
    }

    /**
     * Write key bytes to PEM file
     */
    private void writeKeyToFile(byte[] keyBytes, String filePath, String header, String footer) throws Exception {
        String base64Key = Base64.getEncoder().encodeToString(keyBytes);

        // Format in 64-character lines
        StringBuilder pem = new StringBuilder();
        pem.append(header).append("\n");
        for (int i = 0; i < base64Key.length(); i += 64) {
            pem.append(base64Key, i, Math.min(i + 64, base64Key.length())).append("\n");
        }
        pem.append(footer).append("\n");

        try (FileOutputStream fos = new FileOutputStream(new File(filePath))) {
            fos.write(pem.toString().getBytes());
        }
    }

    /**
     * Read RSAPublic Key from file
     */
    private RSAPublicKey readPublicKey(Resource resource) throws Exception {
        try (InputStream is = resource.getInputStream()) {
            String key = new String(is.readAllBytes())
                    .replace("-----BEGIN PUBLIC KEY-----", "")
                    .replace("-----END PUBLIC KEY-----", "")
                    .replaceAll("\\s", "");

            byte[] keyBytes = Base64.getDecoder().decode(key);
            X509EncodedKeySpec spec = new X509EncodedKeySpec(keyBytes);
            KeyFactory keyFactory = KeyFactory.getInstance("RSA");
            return (RSAPublicKey) keyFactory.generatePublic(spec);
        }
    }

    /**
     * Read RSAPrivate Key from file
     */
    private RSAPrivateKey readPrivateKey(Resource resource) throws Exception {
        try (InputStream is = resource.getInputStream()) {
            String key = new String(is.readAllBytes())
                    .replace("-----BEGIN PRIVATE KEY-----", "")
                    .replace("-----END PRIVATE KEY-----", "")
                    .replaceAll("\\s", "");

            byte[] keyBytes = Base64.getDecoder().decode(key);
            PKCS8EncodedKeySpec spec = new PKCS8EncodedKeySpec(keyBytes);
            KeyFactory keyFactory = KeyFactory.getInstance("RSA");
            return (RSAPrivateKey) keyFactory.generatePrivate(spec);
        }
    }

    /**
     * Configure JWK Source
     */
    @Bean
    public JWKSource<SecurityContext> jwkSource() {
        KeyPair keyPair = keyPair();
        RSAPublicKey publicKey = (RSAPublicKey) keyPair.getPublic();
        RSAPrivateKey privateKey = (RSAPrivateKey) keyPair.getPrivate();

        JWK jwk = new RSAKey.Builder(publicKey)
                .privateKey(privateKey)
                .build();
        JWKSet jwkSet = new JWKSet(jwk);
        return new ImmutableJWKSet<>(jwkSet);
    }

    /**
     * Get the JwtEncoder and JwtDecoder beans
     */
    @Bean
    public JwtEncoder jwtEncoder() {
        return new NimbusJwtEncoder(jwkSource());
    }

    @Bean
    public JwtDecoder jwtDecoder() {
        KeyPair keyPair = keyPair();
        return NimbusJwtDecoder.withPublicKey((RSAPublicKey) keyPair.getPublic()).build();
    }
}
