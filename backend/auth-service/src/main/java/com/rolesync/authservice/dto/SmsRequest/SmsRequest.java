package com.medisecure.authservice.dto.SmsRequest;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class SmsRequest {

    @NotBlank(message = "Phone number is mandatory")
    @Pattern(regexp = "^\\+?[1-9]\\d{1,14}$", message = "Invalid phone number format (E.164)")
    private String to;

    @NotBlank(message = "Message content is mandatory")
    private String message;

    private String fromNumber;
}
