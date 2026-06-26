package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.SavedDashboardLayout;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface SavedDashboardLayoutRepository extends JpaRepository<SavedDashboardLayout, UUID> {
    List<SavedDashboardLayout> findByProfileProfileId(UUID profileId);
    List<SavedDashboardLayout> findByWorkspaceWorkspaceId(UUID workspaceId);
    Optional<SavedDashboardLayout> findByProfileProfileIdAndWorkspaceWorkspaceIdAndIsDefault(UUID profileId, UUID workspaceId, Boolean isDefault);
}
