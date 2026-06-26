package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class WorkspaceContextRequest {

    @NotBlank(message = "Title cannot be blank")
    private String title;

    @JsonProperty("context_type")
    private String contextType;

    private String summary;
}
