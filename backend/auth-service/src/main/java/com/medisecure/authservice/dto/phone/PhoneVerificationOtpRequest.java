package com.medisecure.authservice.dto.phone;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class PhoneVerificationOtpRequest {

    @NotBlank(message = "User ID is required")
    private String userId;

    @NotBlank(message = "OTP is required")
    private String otp;
}

