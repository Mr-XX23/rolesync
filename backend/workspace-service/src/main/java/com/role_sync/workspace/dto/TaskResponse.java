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
public class TaskResponse {

    @JsonProperty("view_id")
    private UUID viewId;

    @JsonProperty("task_name")
    private String taskName;

    @JsonProperty("agent_name")
    private String agentName;

    @JsonProperty("task_status")
    private String taskStatus;

    @JsonProperty("output_type")
    private String outputType;

    @JsonProperty("sort_order")
    private Integer sortOrder;

    @JsonProperty("updated_at")
    private LocalDateTime updatedAt;
}
