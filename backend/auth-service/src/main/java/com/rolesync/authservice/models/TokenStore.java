package com.rolesync.authservice.models;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Column;
import jakarta.persistence.Table;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "token_store")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TokenStore {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(columnDefinition = "UUID", updatable = false, nullable = false)
    private UUID tokenId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "auth_user_id", referencedColumnName = "auth_user_id", nullable = false)
    private AuthUserCredentials authUser;

    @Column(columnDefinition = "UUID", nullable = false)
    private UUID sessionId;

    @Column(columnDefinition = "TEXT", nullable = false)
    private String tokenString;

    @Column(nullable = false)
    private LocalDateTime issuedAt;

    @Column(nullable = false)
    private LocalDateTime expiresAt;

    @Column(length = 128)
    private String deviceFingerprint;

    @Column(length = 64)
    private String deviceName;

    @Column(nullable = false)
    @Builder.Default
    private Boolean revoked = false;

    private LocalDateTime revokedAt;

    @Column(length = 16)
    private String tokenType;
}
