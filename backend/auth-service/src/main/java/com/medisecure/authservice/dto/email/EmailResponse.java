package com.medisecure.authservice.dto.email;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EmailResponse {
    private boolean success;
    private String message;
    private String messageId;
    private LocalDateTime sentAt;
    private int retryAttempts;
}
