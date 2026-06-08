package com.medisecure.authservice.dto.email;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.UUID;

@Data
public class EmailVerificationRequest {

    @NotNull(message = "User ID is required")
    private UUID userId;
}
