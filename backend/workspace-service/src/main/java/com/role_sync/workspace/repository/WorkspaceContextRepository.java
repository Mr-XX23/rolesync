package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceContext;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceContextRepository extends JpaRepository<WorkspaceContext, UUID> {
    List<WorkspaceContext> findByWorkspaceWorkspaceId(UUID workspaceId);

    @Query("SELECT c.workspace.workspaceId FROM WorkspaceContext c WHERE c.contextId = :contextId")
    Optional<UUID> findWorkspaceIdByContextId(@Param("contextId") UUID contextId);
}
