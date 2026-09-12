package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.role_sync.workspace.models.DealContact;
import com.role_sync.workspace.models.DealQuote;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class DealResponse {

    @JsonProperty("deal_id")
    private UUID dealId;

    @JsonProperty("workspace_id")
    private UUID workspaceId;

    private String title;

    private String company;

    private String stage;

    private BigDecimal amount;

    private String currency;

    @JsonProperty("expected_close_date")
    private LocalDate expectedCloseDate;

    @JsonProperty("next_step")
    private String nextStep;

    private String notes;

    private List<DealContact> contacts;

    private List<DealQuote> quotes;

    private String source;

    @JsonProperty("owner_profile_id")
    private UUID ownerProfileId;

    /** The owner's display name, for lists and boards. */
    @JsonProperty("owner_name")
    private String ownerName;

    /** Whether the caller may delete this deal (its owner or a workspace OWNER/ADMIN). */
    @JsonProperty("can_delete")
    private boolean canDelete;

    @JsonProperty("closed_at")
    private LocalDateTime closedAt;

    private Long version;

    @JsonProperty("created_at")
    private LocalDateTime createdAt;

    @JsonProperty("updated_at")
    private LocalDateTime updatedAt;
}
