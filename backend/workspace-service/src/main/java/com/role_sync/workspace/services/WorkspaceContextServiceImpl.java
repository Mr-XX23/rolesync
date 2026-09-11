package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.ContextUpsertRequest;
import com.role_sync.workspace.dto.NoteRequest;
import com.role_sync.workspace.dto.NoteResponse;
import com.role_sync.workspace.dto.NoteUpsertRequest;
import com.role_sync.workspace.dto.TaskUpsertRequest;
import com.role_sync.workspace.dto.WorkspaceContextRequest;
import com.role_sync.workspace.dto.WorkspaceContextResponse;
import com.role_sync.workspace.models.Workspace;
import com.role_sync.workspace.models.WorkspaceContext;
import com.role_sync.workspace.models.WorkspaceNote;
import com.role_sync.workspace.models.WorkspaceProfile;
import com.role_sync.workspace.models.WorkspaceTaskView;
import com.role_sync.workspace.repository.WorkspaceContextRepository;
import com.role_sync.workspace.repository.WorkspaceNoteRepository;
import com.role_sync.workspace.repository.WorkspaceProfileRepository;
import com.role_sync.workspace.repository.WorkspaceRepository;
import com.role_sync.workspace.repository.WorkspaceTaskViewRepository;
import com.role_sync.workspace.services.WorkspaceAuthorizationService.CallerContext;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class WorkspaceContextServiceImpl implements WorkspaceContextService {

    private final WorkspaceRepository workspaceRepository;
    private final WorkspaceProfileRepository workspaceProfileRepository;
    private final WorkspaceContextRepository workspaceContextRepository;
    private final WorkspaceTaskViewRepository workspaceTaskViewRepository;
    private final WorkspaceNoteRepository workspaceNoteRepository;
    private final WorkspaceAuthorizationService authorizationService;

    @Override
    public Mono<WorkspaceContext> createContext(UUID workspaceId, UUID authUserId, WorkspaceContextRequest request) {
        return Mono.fromCallable(() -> {
            // AuthZ: caller must be an active member of this workspace.
            authorizationService.requireActiveMembership(authUserId, workspaceId);

            Workspace workspace = workspaceRepository.findById(workspaceId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace not found"));

            WorkspaceProfile creator = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));

            WorkspaceContext context = WorkspaceContext.builder()
                    .workspace(workspace)
                    .createdBy(creator)
                    .title(request.getTitle())
                    .contextType(request.getContextType())
                    .summary(request.getSummary())
                    .status("ACTIVE")
                    .build();

            return workspaceContextRepository.save(context);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Flux<WorkspaceTaskView> getTasksTimeline(UUID contextId, UUID authUserId) {
        return Mono.fromCallable(() -> {
            // AuthZ: active member of the context's workspace; agent contexts only for their creator.
            requireContextAccess(contextId, authUserId);
            return workspaceTaskViewRepository.findByContextContextIdOrderBySortOrderAsc(contextId);
        })
        .subscribeOn(Schedulers.boundedElastic())
        .flatMapMany(Flux::fromIterable);
    }

    @Override
    public Mono<WorkspaceNote> createNote(UUID contextId, UUID authUserId, NoteRequest request) {
        return Mono.fromCallable(() -> {
            // AuthZ: active member of the context's workspace; agent contexts only for their creator.
            requireContextAccess(contextId, authUserId);

            WorkspaceContext context = workspaceContextRepository.findById(contextId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace context not found"));

            WorkspaceProfile author = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));

            WorkspaceNote note = WorkspaceNote.builder()
                    .workspace(context.getWorkspace())
                    .context(context)
                    .author(author)
                    .noteTitle(request.getNoteTitle())
                    .noteBody(request.getNoteBody())
                    .build();

            return workspaceNoteRepository.save(note);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<UUID> upsertContext(UUID workspaceId, UUID contextId, UUID authUserId, ContextUpsertRequest request) {
        return Mono.fromCallable(() -> {
            CallerContext caller = authorizationService.requireActiveMembership(authUserId, workspaceId);
            int changed = workspaceContextRepository.upsert(contextId, workspaceId, caller.profileId(),
                    request.getTitle(), request.getContextType(), request.getSummary(), request.getStatus());
            if (changed == 0) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "This context id belongs to another context");
            }
            return contextId;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<UUID> upsertTask(UUID contextId, UUID viewId, UUID authUserId, TaskUpsertRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceContextRepository.AccessView context = requireContextAccess(contextId, authUserId);
            int changed = workspaceTaskViewRepository.upsert(viewId, context.getWorkspaceId(), contextId,
                    request.getTaskName(), request.getAgentName(), request.getOutputType(), request.getTaskStatus(),
                    request.getSortOrder() == null ? 0 : request.getSortOrder());
            if (changed == 0) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "This task id belongs to another context");
            }
            return viewId;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Mono<UUID> upsertNote(UUID contextId, UUID noteId, UUID authUserId, NoteUpsertRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceContextRepository.AccessView context = requireContextAccess(contextId, authUserId);
            UUID authorId = authorizationService.requireProfile(authUserId).getProfileId();
            int changed = workspaceNoteRepository.upsert(noteId, context.getWorkspaceId(), contextId, authorId,
                    request.getNoteTitle(), request.getNoteBody());
            if (changed == 0) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "This note id belongs to another note");
            }
            return noteId;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Flux<WorkspaceContextResponse> listMyContexts(UUID workspaceId, UUID authUserId, String contextType) {
        return Mono.fromCallable(() -> {
            CallerContext caller = authorizationService.requireActiveMembership(authUserId, workspaceId);
            List<WorkspaceContext> contexts = (contextType == null || contextType.isBlank())
                    ? workspaceContextRepository.findMine(workspaceId, caller.profileId())
                    : workspaceContextRepository.findMineByType(workspaceId, caller.profileId(), contextType.trim());
            return contexts.stream()
                    .map(context -> WorkspaceContextResponse.builder()
                            .contextId(context.getContextId())
                            .workspaceId(workspaceId)
                            .title(context.getTitle())
                            .contextType(context.getContextType())
                            .summary(context.getSummary())
                            .status(context.getStatus())
                            .createdAt(context.getCreatedAt())
                            .updatedAt(context.getUpdatedAt())
                            .build())
                    .toList();
        })
        .subscribeOn(Schedulers.boundedElastic())
        .flatMapMany(Flux::fromIterable);
    }

    @Override
    public Flux<NoteResponse> listNotes(UUID contextId, UUID authUserId) {
        return Mono.fromCallable(() -> {
            requireContextAccess(contextId, authUserId);
            return workspaceNoteRepository.findByContextContextIdOrderByCreatedAtAsc(contextId).stream()
                    .map(note -> NoteResponse.builder()
                            .noteId(note.getNoteId())
                            .noteTitle(note.getNoteTitle())
                            .noteBody(note.getNoteBody())
                            .createdAt(note.getCreatedAt())
                            .updatedAt(note.getUpdatedAt())
                            .build())
                    .toList();
        })
        .subscribeOn(Schedulers.boundedElastic())
        .flatMapMany(Flux::fromIterable);
    }

    /** Active membership of the context's workspace, plus the agent-context visibility rule. */
    private WorkspaceContextRepository.AccessView requireContextAccess(UUID contextId, UUID authUserId) {
        WorkspaceContextRepository.AccessView context = workspaceContextRepository.findAccessView(contextId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace context not found"));
        CallerContext caller = authorizationService.requireActiveMembership(authUserId, context.getWorkspaceId());
        AgentContextAccess.requireAccess(context.getContextType(), context.getCreatedBy(), caller.profileId());
        return context;
    }
}
