package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.AddMemberRequest;
import com.role_sync.workspace.dto.UpdateMemberRoleRequest;
import com.role_sync.workspace.dto.WorkspaceMembershipResponse;
import com.role_sync.workspace.dto.WorkspaceRequest;
import com.role_sync.workspace.dto.WorkspaceResponse;
import com.role_sync.workspace.models.Workspace;
import com.role_sync.workspace.models.WorkspaceMembership;
import com.role_sync.workspace.models.WorkspaceProfile;
import com.role_sync.workspace.models.WorkspaceRole;
import com.role_sync.workspace.repository.WorkspaceMembershipRepository;
import com.role_sync.workspace.repository.WorkspaceProfileRepository;
import com.role_sync.workspace.repository.WorkspaceRepository;
import com.role_sync.workspace.repository.WorkspaceRoleRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class WorkspaceServiceImpl implements WorkspaceService {

    private final WorkspaceRepository workspaceRepository;
    private final WorkspaceProfileRepository workspaceProfileRepository;
    private final WorkspaceRoleRepository workspaceRoleRepository;
    private final WorkspaceMembershipRepository workspaceMembershipRepository;
    private final WorkspaceAuthorizationService authorizationService;

    @Override
    @Transactional
    public Mono<WorkspaceResponse> createWorkspace(UUID authUserId, WorkspaceRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile ownerProfile = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));

            Workspace workspace = Workspace.builder()
                    .name(request.getName())
                    .description(request.getDescription())
                    .owner(ownerProfile)
                    .isActive(true)
                    .build();
            Workspace savedWorkspace = workspaceRepository.save(workspace);

            // Fetch or create standard OWNER role
            WorkspaceRole ownerRole = workspaceRoleRepository.findByRoleName("OWNER")
                    .orElseGet(() -> workspaceRoleRepository.save(
                            WorkspaceRole.builder()
                                    .roleName("OWNER")
                                    .description("Workspace Owner")
                                    .build()
                    ));

            // Create membership record for the owner
            WorkspaceMembership membership = WorkspaceMembership.builder()
                    .workspace(savedWorkspace)
                    .profile(ownerProfile)
                    .role(ownerRole)
                    .isActive(true)
                    .build();
            workspaceMembershipRepository.save(membership);

            return mapToResponse(savedWorkspace);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    @Transactional(readOnly = true)
    public Flux<WorkspaceResponse> getWorkspacesForUser(UUID authUserId) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));

            List<Workspace> workspaces = workspaceMembershipRepository.findActiveWorkspacesByProfileId(profile.getProfileId());

            if (workspaces == null || workspaces.isEmpty()) {
                workspaces = workspaceRepository.findByOwnerProfileId(profile.getProfileId());
            }

            if (workspaces == null || workspaces.isEmpty()) {
                return Collections.<WorkspaceResponse>emptyList();
            }

            List<WorkspaceResponse> responseList = new ArrayList<>();
            for (Workspace ws : workspaces) {
                if (ws != null) {
                    responseList.add(mapToResponse(ws));
                }
            }
            return responseList;
        })
        .subscribeOn(Schedulers.boundedElastic())
        .flatMapMany(Flux::fromIterable);
    }

    @Override
    @Transactional
    public Mono<UUID> addMemberToWorkspace(UUID workspaceId, UUID callerAuthUserId, AddMemberRequest request) {
        return Mono.fromCallable(() -> {
            // AuthZ: caller must be an OWNER/ADMIN of this workspace.
            WorkspaceAuthorizationService.CallerContext caller =
                    authorizationService.requireAdmin(callerAuthUserId, workspaceId);

            Workspace workspace = workspaceRepository.findById(workspaceId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace not found"));

            WorkspaceProfile memberProfile = workspaceProfileRepository.findById(request.getProfileId())
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Profile to add not found"));

            // Validate the requested role (rejects OWNER / unknown; ADMIN requires caller OWNER).
            String roleName = authorizationService.validateAssignableRole(request.getRoleName(), caller);

            // Cannot alter your own membership through this endpoint (blocks self-escalation).
            if (memberProfile.getProfileId().equals(caller.profileId())) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "You cannot change your own membership");
            }

            // Cannot alter the workspace owner's membership (blocks owner takeover/demotion).
            UUID ownerProfileId = workspaceRepository.findOwnerProfileId(workspaceId).orElse(null);
            if (memberProfile.getProfileId().equals(ownerProfileId)) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Cannot modify the workspace owner's membership");
            }

            WorkspaceRole role = findOrCreateRole(roleName);

            // Check if membership already exists
            WorkspaceMembership membership = workspaceMembershipRepository
                    .findByWorkspaceWorkspaceIdAndProfileProfileId(workspaceId, request.getProfileId())
                    .orElse(null);

            if (membership == null) {
                membership = WorkspaceMembership.builder()
                        .workspace(workspace)
                        .profile(memberProfile)
                        .role(role)
                        .isActive(true)
                        .build();
            } else {
                membership.setRole(role);
                membership.setIsActive(true);
            }

            WorkspaceMembership savedMembership = workspaceMembershipRepository.save(membership);
            return savedMembership.getMembershipId();
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    @Transactional
    public Mono<WorkspaceMembershipResponse> updateMemberRole(UUID workspaceId, UUID membershipId, UUID callerAuthUserId, UpdateMemberRoleRequest request) {
        return Mono.fromCallable(() -> {
            // AuthZ: caller must be an OWNER/ADMIN of this workspace.
            WorkspaceAuthorizationService.CallerContext caller =
                    authorizationService.requireAdmin(callerAuthUserId, workspaceId);

            // Resolve target membership via ID projections (no lazy-proxy navigation).
            UUID membershipWorkspaceId = workspaceMembershipRepository.findWorkspaceIdByMembershipId(membershipId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Membership not found"));
            if (!membershipWorkspaceId.equals(workspaceId)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Membership does not belong to this workspace");
            }
            UUID targetProfileId = workspaceMembershipRepository.findProfileIdByMembershipId(membershipId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Membership not found"));

            // Cannot change your own role (blocks self-escalation).
            if (targetProfileId.equals(caller.profileId())) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "You cannot change your own role");
            }
            // Cannot change the workspace owner's role (blocks owner demotion).
            UUID ownerProfileId = workspaceRepository.findOwnerProfileId(workspaceId).orElse(null);
            if (targetProfileId.equals(ownerProfileId)) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Cannot change the workspace owner's role");
            }

            String roleName = authorizationService.validateAssignableRole(request.getRoleName(), caller);
            WorkspaceRole role = findOrCreateRole(roleName);

            WorkspaceMembership membership = workspaceMembershipRepository.findById(membershipId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Membership not found"));
            membership.setRole(role);
            WorkspaceMembership saved = workspaceMembershipRepository.save(membership);

            // Build response from known values (avoids lazy-proxy navigation on detached entity).
            return WorkspaceMembershipResponse.builder()
                    .membershipId(saved.getMembershipId())
                    .workspaceId(workspaceId)
                    .profileId(targetProfileId)
                    .roleName(roleName)
                    .joinedAt(saved.getJoinedAt())
                    .isActive(saved.getIsActive())
                    .build();
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    @Transactional
    public Mono<WorkspaceResponse> updateWorkspace(UUID workspaceId, UUID authUserId, WorkspaceRequest request) {
        return Mono.fromCallable(() -> {
            // AuthZ: caller must be an OWNER/ADMIN of this workspace.
            authorizationService.requireAdmin(authUserId, workspaceId);

            Workspace workspace = workspaceRepository.findById(workspaceId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace not found"));

            if (request.getName() != null && !request.getName().isBlank()) {
                workspace.setName(request.getName());
            }
            if (request.getDescription() != null) {
                workspace.setDescription(request.getDescription());
            }

            Workspace saved = workspaceRepository.save(workspace);
            return mapToResponse(saved);
        }).subscribeOn(Schedulers.boundedElastic());
    }

    private WorkspaceRole findOrCreateRole(String roleName) {
        return workspaceRoleRepository.findByRoleName(roleName)
                .orElseGet(() -> workspaceRoleRepository.save(
                        WorkspaceRole.builder()
                                .roleName(roleName)
                                .description("Workspace Role: " + roleName)
                                .build()
                ));
    }

    private WorkspaceResponse mapToResponse(Workspace ws) {
        if (ws == null) return null;
        return WorkspaceResponse.builder()
                .workspaceId(ws.getWorkspaceId())
                .name(ws.getName())
                .description(ws.getDescription())
                .isActive(ws.getIsActive())
                .createdAt(ws.getCreatedAt())
                .updatedAt(ws.getUpdatedAt())
                .build();
    }
}
