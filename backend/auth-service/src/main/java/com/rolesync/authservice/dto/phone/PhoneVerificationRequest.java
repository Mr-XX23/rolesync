package com.medisecure.authservice.dto.phone;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.UUID;

@Data
public class PhoneVerificationRequest {
    @NotNull(message = "User ID is required")
    private UUID userId;
}
