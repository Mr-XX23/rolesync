package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceContext;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceContextRepository extends JpaRepository<WorkspaceContext, UUID> {
    List<WorkspaceContext> findByWorkspaceWorkspaceId(UUID workspaceId);

    @Query("SELECT c.workspace.workspaceId FROM WorkspaceContext c WHERE c.contextId = :contextId")
    Optional<UUID> findWorkspaceIdByContextId(@Param("contextId") UUID contextId);

    /** Ids and type only (SQL join, no lazy-proxy navigation): what access checks need. */
    interface AccessView {
        UUID getWorkspaceId();

        UUID getCreatedBy();

        String getContextType();
    }

    @Query("SELECT c.workspace.workspaceId AS workspaceId, c.createdBy.profileId AS createdBy, "
            + "c.contextType AS contextType FROM WorkspaceContext c WHERE c.contextId = :contextId")
    Optional<AccessView> findAccessView(@Param("contextId") UUID contextId);

    @Query("SELECT c FROM WorkspaceContext c WHERE c.workspace.workspaceId = :workspaceId "
            + "AND c.createdBy.profileId = :profileId ORDER BY c.updatedAt DESC")
    List<WorkspaceContext> findMine(@Param("workspaceId") UUID workspaceId, @Param("profileId") UUID profileId);

    @Query("SELECT c FROM WorkspaceContext c WHERE c.workspace.workspaceId = :workspaceId "
            + "AND c.createdBy.profileId = :profileId AND c.contextType = :contextType ORDER BY c.updatedAt DESC")
    List<WorkspaceContext> findMineByType(@Param("workspaceId") UUID workspaceId, @Param("profileId") UUID profileId,
                                          @Param("contextType") String contextType);

    /**
     * Idempotent create-or-update keyed by a caller-chosen id. The update only applies to a
     * row in the same workspace created by the same profile, so a guessed id can't take over
     * someone else's context. Returns 0 when the id belongs to another record.
     */
    @Modifying
    @Transactional
    @Query(value = "INSERT INTO workspace_contexts (context_id, workspace_id, created_by_profile_id, title, "
            + "context_type, summary, status, created_at, updated_at) "
            + "VALUES (:contextId, :workspaceId, :profileId, :title, :contextType, :summary, :status, now(), now()) "
            + "ON CONFLICT (context_id) DO UPDATE SET title = EXCLUDED.title, context_type = EXCLUDED.context_type, "
            + "summary = EXCLUDED.summary, status = EXCLUDED.status, updated_at = now() "
            + "WHERE workspace_contexts.workspace_id = EXCLUDED.workspace_id "
            + "AND workspace_contexts.created_by_profile_id = EXCLUDED.created_by_profile_id",
            nativeQuery = true)
    int upsert(@Param("contextId") UUID contextId, @Param("workspaceId") UUID workspaceId,
               @Param("profileId") UUID profileId, @Param("title") String title,
               @Param("contextType") String contextType, @Param("summary") String summary,
               @Param("status") String status);
}
