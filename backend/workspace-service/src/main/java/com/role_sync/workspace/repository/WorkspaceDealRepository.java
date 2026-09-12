package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceDeal;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceDealRepository extends JpaRepository<WorkspaceDeal, UUID> {

    /** A workspace's deals with their owners loaded (no lazy navigation after the query), newest first. */
    @Query("SELECT d FROM WorkspaceDeal d JOIN FETCH d.owner WHERE d.workspace.workspaceId = :workspaceId "
            + "ORDER BY d.updatedAt DESC")
    List<WorkspaceDeal> findByWorkspaceWithOwner(@Param("workspaceId") UUID workspaceId);

    @Query("SELECT d FROM WorkspaceDeal d JOIN FETCH d.owner WHERE d.dealId = :dealId")
    Optional<WorkspaceDeal> findWithOwner(@Param("dealId") UUID dealId);

    /** The workspace a deal id belongs to (SQL projection), to refuse ids from another workspace. */
    @Query("SELECT d.workspace.workspaceId FROM WorkspaceDeal d WHERE d.dealId = :dealId")
    Optional<UUID> findWorkspaceIdByDealId(@Param("dealId") UUID dealId);
}
