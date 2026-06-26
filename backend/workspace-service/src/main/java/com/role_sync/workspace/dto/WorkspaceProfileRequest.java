package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.util.UUID;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class WorkspaceProfileRequest {

    @NotNull(message = "auth_user_id cannot be null")
    @JsonProperty("auth_user_id")
    private UUID authUserId;

    @JsonProperty("first_name")
    private String firstName;

    @JsonProperty("last_name")
    private String lastName;

    @JsonProperty("job_title")
    private String jobTitle;
}
