package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceAgentAssignment;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceAgentAssignmentRepository extends JpaRepository<WorkspaceAgentAssignment, UUID> {
    List<WorkspaceAgentAssignment> findByWorkspaceWorkspaceId(UUID workspaceId);
    List<WorkspaceAgentAssignment> findByContextContextId(UUID contextId);
    List<WorkspaceAgentAssignment> findByProfileProfileId(UUID profileId);
    List<WorkspaceAgentAssignment> findByWorkspaceWorkspaceIdAndIsActive(UUID workspaceId, Boolean isActive);
}
