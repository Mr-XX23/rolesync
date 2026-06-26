package com.medisecure.authservice.dto.user;

import jakarta.validation.constraints.Pattern;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * DTO for user details request
 * Supports lookup by userId, email, phone, or username
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class UserDetailsRequest {

    @Pattern(regexp = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
             message = "Invalid UUID format")
    private String userId;

    @Pattern(regexp = "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$",
             message = "Invalid email format")
    private String email;

    @Pattern(regexp = "^\\+?[1-9]\\d{1,14}$",
             message = "Invalid phone number format")
    private String phoneNumber;

    @Pattern(regexp = "^[a-zA-Z0-9_]{3,24}$",
             message = "Username must be 3-24 characters and contain only letters, numbers, and underscores")
    private String username;
}

