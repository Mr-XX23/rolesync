package com.medisecure.authservice.models;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "sms_event_log", indexes = {
        @Index(name = "idx_recipient_created", columnList = "recipient, createdAt"),
        @Index(name = "idx_status", columnList = "status")
})
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SmsEventLog {

    public enum SmsStatus {
        PENDING,
        SENT,
        DELIVERED,
        FAILED
    }

    public enum SmsType {
        OTP_VERIFICATION,
        PASSWORD_RESET,
        LOGIN,
        ALERT
    }

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(columnDefinition = "UUID", updatable = false, nullable = false)
    private UUID id;

    @Column(nullable = false, length = 20)
    private String recipient;

    @Column(nullable = false, length = 20)
    private String fromNumber;

    @Column(nullable = false, length = 500)
    private String messageContent;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private SmsType smsType;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private SmsStatus status;

    // removed messageSid, errorMessage, errorCode and retryAttempts per simplified schema

    @Column(precision = 10, scale = 4)
    private BigDecimal cost;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    private LocalDateTime deliveredAt;

    @Column(name = "auth_user_id")
    private UUID authUserId;

    @Column(nullable = false)
    @Builder.Default
    private boolean isOtp = false;

    // countryCode removed per simplified schema
}