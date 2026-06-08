package com.medisecure.authservice.dto.loginregistration;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OAuth2LoginResponse {

    private String accessToken;
    private String refreshToken;
    private String userId;
    private String email;
    private String name;
    private boolean isNewUser;
    private String message;

}
