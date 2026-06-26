package com.medisecure.authservice.dto.email;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class EmailRequest {

    @NotBlank(message = "Recipient email is mandatory")
    @Email(message = "Invalid email format")
    private String to;

    @NotBlank(message = "Subject is mandatory")
    private String subject;

    private String templateName;

    private Map<String, Object> templateVariables;

    private String plainTextContent;

    private String htmlContent;

    private boolean isHtml;

    private String replyTo;

}
