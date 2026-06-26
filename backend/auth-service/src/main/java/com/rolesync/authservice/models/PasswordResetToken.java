package com.rolesync.authservice.models;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "password_reset_tokens")
@Getter
@Setter
@NoArgsConstructor
public class PasswordResetToken {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(nullable = false, unique = true)
    private String token;

    @OneToOne
    @JoinColumn(name = "auth_user_id", nullable = false)
    private AuthUserCredentials authUser;

    @Column(length = 32, nullable = false)
    private String purpose;

    @Column(nullable = false)
    private Boolean used = false;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    private LocalDateTime usedAt;

    @Column(nullable = false)
    private LocalDateTime expiryDate;

    public boolean isExpired() {
        return LocalDateTime.now().isAfter(expiryDate);
    }
}
