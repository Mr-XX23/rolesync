package com.medisecure.authservice.models;

import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
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
@Table(name = "security_events")
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AuthSecurityEvent {
    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(columnDefinition = "UUID", updatable = false, nullable = false)
    private UUID eventId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "auth_user_id", nullable = true)
    private AuthUserCredentials authUser;

    @Column(length = 32, nullable = false)
    private String eventType;

    @Column(columnDefinition = "TEXT")
    private String eventData;

    @Column(nullable = false)
    private LocalDateTime eventTime;

    @Column(length = 45)
    private String ipAddress;

    @Column(length = 255)
    private String userAgent;
}
