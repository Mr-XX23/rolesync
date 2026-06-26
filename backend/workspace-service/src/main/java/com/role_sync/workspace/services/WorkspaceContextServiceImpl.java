package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.NoteRequest;
import com.role_sync.workspace.dto.WorkspaceContextRequest;
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

    @Override
    public Mono<WorkspaceContext> createContext(UUID workspaceId, UUID authUserId, WorkspaceContextRequest request) {
        return Mono.fromCallable(() -> {
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
    public Flux<WorkspaceTaskView> getTasksTimeline(UUID contextId) {
        return Mono.fromCallable(() -> {
            return workspaceTaskViewRepository.findByContextContextIdOrderBySortOrderAsc(contextId);
        })
        .subscribeOn(Schedulers.boundedElastic())
        .flatMapMany(Flux::fromIterable);
    }

    @Override
    public Mono<WorkspaceNote> createNote(UUID contextId, UUID authUserId, NoteRequest request) {
        return Mono.fromCallable(() -> {
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
}
