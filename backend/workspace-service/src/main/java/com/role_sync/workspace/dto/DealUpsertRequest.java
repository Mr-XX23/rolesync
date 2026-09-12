package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.role_sync.workspace.models.DealContact;
import com.role_sync.workspace.models.DealQuote;
import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * Create-or-replace of a deal, keyed by a caller-chosen id. Every field is sent (a full
 * replace); {@code expected_version}, when given, must match the stored version or the write
 * is refused with 409, so two people (or agents) editing at once can't overwrite each other.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class DealUpsertRequest {

    @NotBlank(message = "title cannot be blank")
    @Size(max = 200)
    private String title;

    @NotBlank(message = "company cannot be blank")
    @Size(max = 200)
    private String company;

    @NotBlank(message = "stage cannot be blank")
    @Pattern(regexp = "(?i)^(PROSPECTING|QUALIFIED|PROPOSAL|NEGOTIATION|WON|LOST)$",
            message = "stage must be PROSPECTING, QUALIFIED, PROPOSAL, NEGOTIATION, WON or LOST")
    private String stage;

    @DecimalMin(value = "0", message = "amount cannot be negative")
    @Digits(integer = 13, fraction = 2, message = "amount can have at most 13 digits and 2 decimals")
    private BigDecimal amount;

    @Pattern(regexp = "^[A-Z]{3}$", message = "currency must be a 3-letter code such as USD")
    private String currency;

    @JsonProperty("expected_close_date")
    private LocalDate expectedCloseDate;

    @Size(max = 500)
    @JsonProperty("next_step")
    private String nextStep;

    @Size(max = 10000)
    private String notes;

    @Valid
    @Size(max = 20, message = "a deal can list at most 20 contacts")
    private List<DealContact> contacts;

    @Valid
    @Size(max = 50, message = "a deal can list at most 50 quotes")
    private List<DealQuote> quotes;

    /** MANUAL (default) or AGENT. */
    @Pattern(regexp = "(?i)^(MANUAL|AGENT)$", message = "source must be MANUAL or AGENT")
    private String source;

    @JsonProperty("expected_version")
    private Long expectedVersion;
}
