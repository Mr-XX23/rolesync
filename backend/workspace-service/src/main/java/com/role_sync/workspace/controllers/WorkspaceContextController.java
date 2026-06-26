package com.role_sync.workspace.controllers;

import com.role_sync.workspace.dto.NoteRequest;
import com.role_sync.workspace.dto.TaskResponse;
import com.role_sync.workspace.dto.WorkspaceContextRequest;
import com.role_sync.workspace.services.WorkspaceContextService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/workspaces")
@RequiredArgsConstructor
public class WorkspaceContextController {

    private final WorkspaceContextService workspaceContextService;

    @PostMapping("/{workspaceId}/contexts")
    public Mono<ResponseEntity<Map<String, Object>>> createContext(
            @PathVariable UUID workspaceId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody WorkspaceContextRequest request) {

        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.createContext(workspaceId, authUserId, request)
                .map(context -> ResponseEntity.status(HttpStatus.CREATED)
                        .body(Map.of(
                                "context_id", context.getContextId(),
                                "message", "Workspace context created successfully"
                        )));
    }

    @GetMapping("/contexts/{contextId}/tasks")
    public Flux<TaskResponse> getTasksTimeline(@PathVariable UUID contextId) {
        return workspaceContextService.getTasksTimeline(contextId)
                .map(view -> TaskResponse.builder()
                        .taskName(view.getTaskName())
                        .agentName(view.getAgentName())
                        .taskStatus(view.getTaskStatus())
                        .outputType(view.getOutputType())
                        .build());
    }

    @PostMapping("/contexts/{contextId}/notes")
    public Mono<ResponseEntity<Map<String, Object>>> createNote(
            @PathVariable UUID contextId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody NoteRequest request) {

        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.createNote(contextId, authUserId, request)
                .map(note -> ResponseEntity.status(HttpStatus.CREATED)
                        .body(Map.of(
                                "note_id", note.getNoteId(),
                                "message", "Note saved to context successfully"
                        )));
    }

    private UUID resolveAuthUserId(String userIdHeader, String authUserIdHeader) {
        String idStr = userIdHeader != null ? userIdHeader : authUserIdHeader;
        if (idStr == null || idStr.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,
                    "Missing user identification header (X-User-Id or X-Auth-User-Id)");
        }
        try {
            return UUID.fromString(idStr);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Invalid UUID format in user identification header");
        }
    }
}
