package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceProfile;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceProfileRepository extends JpaRepository<WorkspaceProfile, UUID> {
    Optional<WorkspaceProfile> findByAuthUserId(UUID authUserId);

    /** The profile row, locked until the surrounding transaction ends (serializes per-user provisioning). */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT p FROM WorkspaceProfile p WHERE p.profileId = :profileId")
    Optional<WorkspaceProfile> lockByProfileId(@Param("profileId") UUID profileId);
}
