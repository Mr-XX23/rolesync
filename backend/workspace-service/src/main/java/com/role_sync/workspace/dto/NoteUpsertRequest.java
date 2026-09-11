package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/** Create-or-update of a note on a context, keyed by a caller-chosen id. */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class NoteUpsertRequest {

    @NotBlank(message = "note_title cannot be blank")
    @Size(max = 150)
    @JsonProperty("note_title")
    private String noteTitle;

    @NotBlank(message = "note_body cannot be blank")
    @JsonProperty("note_body")
    private String noteBody;
}
