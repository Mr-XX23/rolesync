package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.UUID;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WorkspaceMembershipResponse {

    @JsonProperty("membershipId")
    private UUID membershipId;

    @JsonProperty("workspaceId")
    private UUID workspaceId;

    @JsonProperty("profileId")
    private UUID profileId;

    @JsonProperty("roleName")
    private String roleName;

    @JsonProperty("joinedAt")
    private LocalDateTime joinedAt;

    @JsonProperty("isActive")
    private Boolean isActive;
}
