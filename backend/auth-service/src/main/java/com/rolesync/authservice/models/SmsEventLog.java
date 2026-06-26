package com.rolesync.authservice.models;

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
        FAILED,
        QUEUED,
        UNDELIVERED
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

    @Column(length = 50)
    private String messageSid;

    @Column(columnDefinition = "TEXT")
    private String errorMessage;

    @Column(length = 10)
    private String errorCode;

    @Column(nullable = false)
    @Builder.Default
    private int retryAttempts = 0;

    @Column(precision = 10, scale = 4)
    private BigDecimal cost;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    private LocalDateTime sentAt;

    private LocalDateTime deliveredAt;

    @Column(name = "auth_user_id")
    private UUID authUserId;

    @Column(nullable = false)
    @Builder.Default
    private boolean isOtp = false;

    @Column(length = 5)
    private String countryCode;
}