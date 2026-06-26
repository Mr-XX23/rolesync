package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.Workspace;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceRepository extends JpaRepository<Workspace, UUID> {
    List<Workspace> findByOwnerProfileId(UUID ownerProfileId);
    List<Workspace> findByIsActive(Boolean isActive);
}
