package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceTaskView;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceTaskViewRepository extends JpaRepository<WorkspaceTaskView, UUID> {
    List<WorkspaceTaskView> findByWorkspaceWorkspaceId(UUID workspaceId);
    List<WorkspaceTaskView> findByContextContextIdOrderBySortOrderAsc(UUID contextId);
}
