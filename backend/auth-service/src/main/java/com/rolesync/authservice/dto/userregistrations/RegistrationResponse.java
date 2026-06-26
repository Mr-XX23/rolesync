package com.medisecure.authservice.dto.userregistrations;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Builder;
import lombok.Data;

@JsonInclude(JsonInclude.Include.NON_NULL)
@Data
@Builder
public class RegistrationResponse {

    private boolean success;
    private String message;
    private String userId;
    private String username;
    private Boolean emailVerificationSent;
    private Boolean smsVerificationSent;
    private String email;

}
