package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceProfile;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceProfileRepository extends JpaRepository<WorkspaceProfile, UUID> {
    Optional<WorkspaceProfile> findByAuthUserId(UUID authUserId);
}
