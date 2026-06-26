package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspacePreferences;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspacePreferencesRepository extends JpaRepository<WorkspacePreferences, UUID> {
    Optional<WorkspacePreferences> findByProfileProfileId(UUID profileId);
}
