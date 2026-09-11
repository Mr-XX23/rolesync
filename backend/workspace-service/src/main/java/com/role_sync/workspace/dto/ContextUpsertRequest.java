package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Create-or-update of a context whose id the caller chose (idempotent for retries). */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ContextUpsertRequest {

    @NotBlank(message = "title cannot be blank")
    @Size(max = 150)
    private String title;

    @JsonProperty("context_type")
    @Size(max = 50)
    private String contextType;

    private String summary;

    @Size(max = 30)
    private String status;
}
