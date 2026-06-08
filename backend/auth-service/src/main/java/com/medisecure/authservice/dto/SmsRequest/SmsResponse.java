package com.medisecure.authservice.dto.SmsRequest;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SmsResponse {
    private boolean success;
    private String message;
    private String messageSid;
    private String status;
    private LocalDateTime sentAt;
    private int retryAttempts;
    private BigDecimal cost;
    private String errorCode;
}
