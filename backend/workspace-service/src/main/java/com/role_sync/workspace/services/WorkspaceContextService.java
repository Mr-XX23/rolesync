package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.ContextUpsertRequest;
import com.role_sync.workspace.dto.NoteRequest;
import com.role_sync.workspace.dto.NoteResponse;
import com.role_sync.workspace.dto.NoteUpsertRequest;
import com.role_sync.workspace.dto.TaskUpsertRequest;
import com.role_sync.workspace.dto.WorkspaceContextRequest;
import com.role_sync.workspace.dto.WorkspaceContextResponse;
import com.role_sync.workspace.models.WorkspaceContext;
import com.role_sync.workspace.models.WorkspaceNote;
import com.role_sync.workspace.models.WorkspaceTaskView;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.UUID;

public interface WorkspaceContextService {
    Mono<WorkspaceContext> createContext(UUID workspaceId, UUID authUserId, WorkspaceContextRequest request);
    Flux<WorkspaceTaskView> getTasksTimeline(UUID contextId, UUID authUserId);
    Mono<WorkspaceNote> createNote(UUID contextId, UUID authUserId, NoteRequest request);

    // Idempotent writes with caller-chosen ids (used by the sales agent engine to record its work).
    Mono<UUID> upsertContext(UUID workspaceId, UUID contextId, UUID authUserId, ContextUpsertRequest request);
    Mono<UUID> upsertTask(UUID contextId, UUID viewId, UUID authUserId, TaskUpsertRequest request);
    Mono<UUID> upsertNote(UUID contextId, UUID noteId, UUID authUserId, NoteUpsertRequest request);

    /** The caller's own contexts in a workspace, newest first, optionally of one type. */
    Flux<WorkspaceContextResponse> listMyContexts(UUID workspaceId, UUID authUserId, String contextType);
    Flux<NoteResponse> listNotes(UUID contextId, UUID authUserId);
}
