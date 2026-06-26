package com.role_sync.workspace.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class WorkspaceRequest {

    @NotBlank(message = "Workspace name cannot be blank")
    private String name;

    private String description;
}
