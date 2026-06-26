package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.AddMemberRequest;
import com.role_sync.workspace.dto.UpdateMemberRoleRequest;
import com.role_sync.workspace.dto.WorkspaceRequest;
import com.role_sync.workspace.models.Workspace;
import com.role_sync.workspace.models.WorkspaceMembership;
import com.role_sync.workspace.models.WorkspaceProfile;
import com.role_sync.workspace.models.WorkspaceRole;
import com.role_sync.workspace.repository.WorkspaceMembershipRepository;
import com.role_sync.workspace.repository.WorkspaceProfileRepository;
import com.role_sync.workspace.repository.WorkspaceRepository;
import com.role_sync.workspace.repository.WorkspaceRoleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.List;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class WorkspaceServiceImpl implements WorkspaceService {

    private final WorkspaceRepository workspaceRepository;
    private final WorkspaceProfileRepository workspaceProfileRepository;
    private final WorkspaceRoleRepository workspaceRoleRepository;
    private final WorkspaceMembershipRepository workspaceMembershipRepository;

    @Override
    public Mono<Workspace> createWorkspace(UUID authUserId, WorkspaceRequest request) {
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

            return savedWorkspace;
        }).subscribeOn(Schedulers.boundedElastic());
    }

    @Override
    public Flux<Workspace> getWorkspacesForUser(UUID authUserId) {
        return Mono.fromCallable(() -> {
            WorkspaceProfile profile = workspaceProfileRepository.findByAuthUserId(authUserId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace profile not found"));
            List<WorkspaceMembership> memberships = workspaceMembershipRepository.findByProfileProfileId(profile.getProfileId());
            return memberships.stream()
                    .filter(WorkspaceMembership::getIsActive)
                    .map(WorkspaceMembership::getWorkspace)
                    .toList();
        })
        .subscribeOn(Schedulers.boundedElastic())
        .flatMapMany(Flux::fromIterable);
    }

    @Override
    public Mono<UUID> addMemberToWorkspace(UUID workspaceId, AddMemberRequest request) {
        return Mono.fromCallable(() -> {
            Workspace workspace = workspaceRepository.findById(workspaceId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace not found"));

            WorkspaceProfile memberProfile = workspaceProfileRepository.findById(request.getProfileId())
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Profile to add not found"));

            String roleName = request.getRoleName() != null ? request.getRoleName() : "MEMBER";
            WorkspaceRole role = workspaceRoleRepository.findByRoleName(roleName)
                    .orElseGet(() -> workspaceRoleRepository.save(
                            WorkspaceRole.builder()
                                    .roleName(roleName)
                                    .description("Workspace Role: " + roleName)
                                    .build()
                    ));

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
    public Mono<WorkspaceMembership> updateMemberRole(UUID workspaceId, UUID membershipId, UpdateMemberRoleRequest request) {
        return Mono.fromCallable(() -> {
            WorkspaceMembership membership = workspaceMembershipRepository.findById(membershipId)
                    .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Membership not found"));

            if (!membership.getWorkspace().getWorkspaceId().equals(workspaceId)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Membership does not belong to this workspace");
            }

            WorkspaceRole role = workspaceRoleRepository.findByRoleName(request.getRoleName())
                    .orElseGet(() -> workspaceRoleRepository.save(
                            WorkspaceRole.builder()
                                    .roleName(request.getRoleName())
                                    .description("Workspace Role: " + request.getRoleName())
                                    .build()
                    ));

            membership.setRole(role);
            return workspaceMembershipRepository.save(membership);
        }).subscribeOn(Schedulers.boundedElastic());
    }
}
