package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.NoteRequest;
import com.role_sync.workspace.dto.WorkspaceContextRequest;
import com.role_sync.workspace.models.WorkspaceContext;
import com.role_sync.workspace.models.WorkspaceNote;
import com.role_sync.workspace.models.WorkspaceTaskView;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.UUID;

public interface WorkspaceContextService {
    Mono<WorkspaceContext> createContext(UUID workspaceId, UUID authUserId, WorkspaceContextRequest request);
    Flux<WorkspaceTaskView> getTasksTimeline(UUID contextId);
    Mono<WorkspaceNote> createNote(UUID contextId, UUID authUserId, NoteRequest request);
}
