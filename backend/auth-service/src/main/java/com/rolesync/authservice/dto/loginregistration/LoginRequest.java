package com.medisecure.authservice.dto.loginregistration;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class LoginRequest {
    @NotBlank(message = "Email/Username is required")
    private String username;

    @NotBlank(message = "Password is required")
    private String password;
}
