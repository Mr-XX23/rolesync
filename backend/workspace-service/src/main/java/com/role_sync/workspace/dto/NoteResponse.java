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
public class NoteResponse {

    @JsonProperty("note_id")
    private UUID noteId;

    @JsonProperty("note_title")
    private String noteTitle;

    @JsonProperty("note_body")
    private String noteBody;

    @JsonProperty("created_at")
    private LocalDateTime createdAt;

    @JsonProperty("updated_at")
    private LocalDateTime updatedAt;
}
