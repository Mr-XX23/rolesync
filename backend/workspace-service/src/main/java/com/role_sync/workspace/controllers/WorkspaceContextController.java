package com.role_sync.workspace.controllers;

import com.role_sync.workspace.dto.ContextUpsertRequest;
import com.role_sync.workspace.dto.NoteRequest;
import com.role_sync.workspace.dto.NoteResponse;
import com.role_sync.workspace.dto.NoteUpsertRequest;
import com.role_sync.workspace.dto.TaskResponse;
import com.role_sync.workspace.dto.TaskUpsertRequest;
import com.role_sync.workspace.dto.WorkspaceContextRequest;
import com.role_sync.workspace.dto.WorkspaceContextResponse;
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
    public Flux<TaskResponse> getTasksTimeline(
            @PathVariable UUID contextId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.getTasksTimeline(contextId, authUserId)
                .map(view -> TaskResponse.builder()
                        .viewId(view.getViewId())
                        .taskName(view.getTaskName())
                        .agentName(view.getAgentName())
                        .taskStatus(view.getTaskStatus())
                        .outputType(view.getOutputType())
                        .sortOrder(view.getSortOrder())
                        .updatedAt(view.getUpdatedAt())
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

    // ---------------------------------------------------------------------------------------
    // Idempotent upserts with caller-chosen ids. The sales agent engine records its work here
    // (a session as a context, its actions as tasks, its outputs as notes) and retries safely.
    // ---------------------------------------------------------------------------------------

    @PutMapping("/{workspaceId}/contexts/{contextId}")
    public Mono<Map<String, Object>> upsertContext(
            @PathVariable UUID workspaceId,
            @PathVariable UUID contextId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody ContextUpsertRequest request) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.upsertContext(workspaceId, contextId, authUserId, request)
                .map(id -> Map.of("context_id", id));
    }

    @GetMapping("/{workspaceId}/contexts")
    public Flux<WorkspaceContextResponse> listMyContexts(
            @PathVariable UUID workspaceId,
            @RequestParam(value = "type", required = false) String contextType,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.listMyContexts(workspaceId, authUserId, contextType);
    }

    @PutMapping("/contexts/{contextId}/tasks/{viewId}")
    public Mono<Map<String, Object>> upsertTask(
            @PathVariable UUID contextId,
            @PathVariable UUID viewId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody TaskUpsertRequest request) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.upsertTask(contextId, viewId, authUserId, request)
                .map(id -> Map.of("view_id", id));
    }

    @PutMapping("/contexts/{contextId}/notes/{noteId}")
    public Mono<Map<String, Object>> upsertNote(
            @PathVariable UUID contextId,
            @PathVariable UUID noteId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody NoteUpsertRequest request) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.upsertNote(contextId, noteId, authUserId, request)
                .map(id -> Map.of("note_id", id));
    }

    @GetMapping("/contexts/{contextId}/notes")
    public Flux<NoteResponse> listNotes(
            @PathVariable UUID contextId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {
        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceContextService.listNotes(contextId, authUserId);
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
