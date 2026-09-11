package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.Workspace;
import com.role_sync.workspace.models.WorkspaceMembership;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceMembershipRepository extends JpaRepository<WorkspaceMembership, UUID> {
    List<WorkspaceMembership> findByWorkspaceWorkspaceId(UUID workspaceId);
    List<WorkspaceMembership> findByProfileProfileId(UUID profileId);

    @Query("SELECT wm.workspace FROM WorkspaceMembership wm WHERE wm.profile.profileId = :profileId AND wm.isActive = true")
    List<Workspace> findActiveWorkspacesByProfileId(@Param("profileId") UUID profileId);

    @Query("SELECT wm FROM WorkspaceMembership wm JOIN FETCH wm.workspace w WHERE wm.profile.profileId = :profileId AND wm.isActive = true")
    List<WorkspaceMembership> findActiveMembershipsWithWorkspace(@Param("profileId") UUID profileId);

    Optional<WorkspaceMembership> findByWorkspaceWorkspaceIdAndProfileProfileId(UUID workspaceId, UUID profileId);

    // --- Authorization projections (resolved as SQL joins; no lazy-proxy navigation) ---

    @Query("SELECT wm.role.roleName FROM WorkspaceMembership wm " +
           "WHERE wm.workspace.workspaceId = :workspaceId AND wm.profile.profileId = :profileId AND wm.isActive = true")
    Optional<String> findActiveRoleName(@Param("workspaceId") UUID workspaceId, @Param("profileId") UUID profileId);

    @Query("SELECT wm.workspace.workspaceId FROM WorkspaceMembership wm WHERE wm.membershipId = :membershipId")
    Optional<UUID> findWorkspaceIdByMembershipId(@Param("membershipId") UUID membershipId);

    @Query("SELECT wm.profile.profileId FROM WorkspaceMembership wm WHERE wm.membershipId = :membershipId")
    Optional<UUID> findProfileIdByMembershipId(@Param("membershipId") UUID membershipId);
}
