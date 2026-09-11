package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Create-or-update of a task on a context's timeline, keyed by a caller-chosen id. */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class TaskUpsertRequest {

    @NotBlank(message = "task_name cannot be blank")
    @Size(max = 150)
    @JsonProperty("task_name")
    private String taskName;

    @Size(max = 100)
    @JsonProperty("agent_name")
    private String agentName;

    @Size(max = 50)
    @JsonProperty("output_type")
    private String outputType;

    @Size(max = 30)
    @JsonProperty("task_status")
    private String taskStatus;

    @JsonProperty("sort_order")
    private Integer sortOrder;
}
