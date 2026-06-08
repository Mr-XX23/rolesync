package com.medisecure.authservice.dto.user;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.medisecure.authservice.models.Role;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * DTO for user details response
 * Excludes sensitive information like password hash
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class UserDetailsResponse {

    private String userId;
    private String username;
    private String usernameId;
    private String email;
    private String phoneNumber;
    private Role role;
    private String status;
    private String loginType;
    private boolean emailVerified;
    private boolean phoneVerified;
    private boolean mfaEnabled;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private LocalDateTime lastLoginAt;

    // Additional metadata
    private String message;
    private boolean success;
    private Long timestamp;
}

