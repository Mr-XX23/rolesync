package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceMembership;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceMembershipRepository extends JpaRepository<WorkspaceMembership, UUID> {
    List<WorkspaceMembership> findByWorkspaceWorkspaceId(UUID workspaceId);
    List<WorkspaceMembership> findByProfileProfileId(UUID profileId);
    Optional<WorkspaceMembership> findByWorkspaceWorkspaceIdAndProfileProfileId(UUID workspaceId, UUID profileId);
}
