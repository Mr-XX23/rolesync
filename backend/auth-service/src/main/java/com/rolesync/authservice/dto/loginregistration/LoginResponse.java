package com.medisecure.authservice.dto.loginregistration;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class LoginResponse {

    @NotBlank(message = "Username is needed")
    private String message;

    @NotBlank(message = "username is needed")
    private String username;

    private String userId;

    private String email;

    private String phoneNumber;

    private String LastLoginTime;

    @NotBlank(message = "status is needed")
    private String status;

    @NotBlank(message = "role is needed")
    private String role;

    @NotBlank(message = "code is needed")
    private String statusCode;

}
