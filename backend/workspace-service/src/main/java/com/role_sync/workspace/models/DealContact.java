package com.role_sync.workspace.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/** A person on the customer's side of a deal (stored in the deal's {@code contacts} JSON column). */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonIgnoreProperties(ignoreUnknown = true)
public class DealContact {

    @NotBlank(message = "contact name cannot be blank")
    @Size(max = 150)
    private String name;

    @Email(message = "contact email must be a valid email address")
    @Size(max = 320)
    private String email;

    @Size(max = 100)
    private String role;

    @Size(max = 40)
    private String phone;
}
