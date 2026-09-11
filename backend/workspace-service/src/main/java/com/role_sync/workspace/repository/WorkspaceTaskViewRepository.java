package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceTaskView;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceTaskViewRepository extends JpaRepository<WorkspaceTaskView, UUID> {
    List<WorkspaceTaskView> findByWorkspaceWorkspaceId(UUID workspaceId);
    List<WorkspaceTaskView> findByContextContextIdOrderBySortOrderAsc(UUID contextId);

    /**
     * Idempotent create-or-update keyed by a caller-chosen id; an existing id is only updated
     * when it belongs to the same context. Returns 0 when the id belongs to another record.
     */
    @Modifying
    @Transactional
    @Query(value = "INSERT INTO workspace_task_views (view_id, workspace_id, context_id, task_name, agent_name, "
            + "output_type, task_status, sort_order, created_at, updated_at) "
            + "VALUES (:viewId, :workspaceId, :contextId, :taskName, :agentName, :outputType, :taskStatus, "
            + ":sortOrder, now(), now()) "
            + "ON CONFLICT (view_id) DO UPDATE SET task_name = EXCLUDED.task_name, agent_name = EXCLUDED.agent_name, "
            + "output_type = EXCLUDED.output_type, task_status = EXCLUDED.task_status, "
            + "sort_order = EXCLUDED.sort_order, updated_at = now() "
            + "WHERE workspace_task_views.context_id = EXCLUDED.context_id",
            nativeQuery = true)
    int upsert(@Param("viewId") UUID viewId, @Param("workspaceId") UUID workspaceId,
               @Param("contextId") UUID contextId, @Param("taskName") String taskName,
               @Param("agentName") String agentName, @Param("outputType") String outputType,
               @Param("taskStatus") String taskStatus, @Param("sortOrder") Integer sortOrder);
}
