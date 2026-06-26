package com.rolesync.authservice.models;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Column;
import jakarta.persistence.UniqueConstraint;
import jakarta.persistence.Table;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.Enumerated;
import jakarta.persistence.EnumType;
import jakarta.validation.constraints.Email;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;
import org.springframework.data.annotation.CreatedDate;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "oauth_identity",
        uniqueConstraints = @UniqueConstraint(columnNames = {"provider", "providerUserId"}))
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class OauthIdentity {

    public enum Provider {
        GOOGLE,
        FACEBOOK,
        LINKEDIN
    }

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(columnDefinition = "UUID", updatable = false, nullable = false)
    private UUID oauthId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "auth_user_id", nullable = false)
    private AuthUserCredentials authUser;

    @Column(length = 16, nullable = false)
    @Enumerated(EnumType.STRING)
    private Provider provider;

    @Column(length = 128, nullable = false)
    private String providerUserId;

    @Email
    @Column(length = 100)
    private String email;

    private String avatarUrl;

    private LocalDateTime linkedAt;

    @CreatedDate
    private LocalDateTime createdAt;

    private LocalDateTime lastLoginAt;

}
