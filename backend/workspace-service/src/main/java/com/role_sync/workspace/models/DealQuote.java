package com.role_sync.workspace.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;

/** A quote sent for a deal (stored in the deal's {@code quotes} JSON column). */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonIgnoreProperties(ignoreUnknown = true)
public class DealQuote {

    @NotBlank(message = "quote number cannot be blank")
    @Size(max = 60)
    private String number;

    @DecimalMin(value = "0", message = "quote total cannot be negative")
    private BigDecimal total;

    @Pattern(regexp = "^[A-Z]{3}$", message = "currency must be a 3-letter code")
    private String currency;

    /** Where the quote document lives (Google Drive or a knowledge-vault page). */
    @Size(max = 1000)
    private String link;

    @Size(max = 40)
    @JsonProperty("created_at")
    private String createdAt;
}
