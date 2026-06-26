package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceContext;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceContextRepository extends JpaRepository<WorkspaceContext, UUID> {
    List<WorkspaceContext> findByWorkspaceWorkspaceId(UUID workspaceId);
}
