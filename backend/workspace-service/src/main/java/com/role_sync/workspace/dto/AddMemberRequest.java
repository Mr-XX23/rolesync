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
public class AddMemberRequest {

    @NotNull(message = "profile_id cannot be null")
    @JsonProperty("profile_id")
    private UUID profileId;

    @JsonProperty("role_name")
    private String roleName;
}
