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
public class WorkspaceContextResponse {

    @JsonProperty("context_id")
    private UUID contextId;

    @JsonProperty("workspace_id")
    private UUID workspaceId;

    @JsonProperty("title")
    private String title;

    @JsonProperty("context_type")
    private String contextType;

    @JsonProperty("summary")
    private String summary;

    @JsonProperty("status")
    private String status;

    @JsonProperty("created_at")
    private LocalDateTime createdAt;

    @JsonProperty("updated_at")
    private LocalDateTime updatedAt;
}
