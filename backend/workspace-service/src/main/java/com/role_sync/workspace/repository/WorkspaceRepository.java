package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.Workspace;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceRepository extends JpaRepository<Workspace, UUID> {
    @Query("SELECT w FROM Workspace w WHERE w.owner.profileId = :ownerProfileId AND w.isActive = true")
    List<Workspace> findByOwnerProfileId(@Param("ownerProfileId") UUID ownerProfileId);

    List<Workspace> findByIsActive(Boolean isActive);

    @Query("SELECT w.owner.profileId FROM Workspace w WHERE w.workspaceId = :workspaceId")
    java.util.Optional<UUID> findOwnerProfileId(@Param("workspaceId") UUID workspaceId);
}
