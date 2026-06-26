package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class TaskResponse {

    @JsonProperty("task_name")
    private String taskName;

    @JsonProperty("agent_name")
    private String agentName;

    @JsonProperty("task_status")
    private String taskStatus;

    @JsonProperty("output_type")
    private String outputType;
}
