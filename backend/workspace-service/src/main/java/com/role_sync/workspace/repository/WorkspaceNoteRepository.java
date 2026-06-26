package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceNote;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceNoteRepository extends JpaRepository<WorkspaceNote, UUID> {
    List<WorkspaceNote> findByWorkspaceWorkspaceId(UUID workspaceId);
    List<WorkspaceNote> findByContextContextId(UUID contextId);
}
