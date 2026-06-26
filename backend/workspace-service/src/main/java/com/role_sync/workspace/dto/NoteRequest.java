package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class NoteRequest {

    @NotBlank(message = "note_title cannot be blank")
    @JsonProperty("note_title")
    private String noteTitle;

    @NotBlank(message = "note_body cannot be blank")
    @JsonProperty("note_body")
    private String noteBody;
}
