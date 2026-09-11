package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.AddMemberRequest;
import com.role_sync.workspace.dto.UpdateMemberRoleRequest;
import com.role_sync.workspace.dto.WorkspaceMembershipResponse;
import com.role_sync.workspace.dto.WorkspaceRequest;
import com.role_sync.workspace.dto.WorkspaceResponse;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.UUID;

public interface WorkspaceService {
    Mono<WorkspaceResponse> createWorkspace(UUID authUserId, WorkspaceRequest request);
    Flux<WorkspaceResponse> getWorkspacesForUser(UUID authUserId);
    Mono<UUID> addMemberToWorkspace(UUID workspaceId, UUID callerAuthUserId, AddMemberRequest request);
    Mono<WorkspaceMembershipResponse> updateMemberRole(UUID workspaceId, UUID membershipId, UUID callerAuthUserId, UpdateMemberRoleRequest request);
    Mono<WorkspaceResponse> updateWorkspace(UUID workspaceId, UUID authUserId, WorkspaceRequest request);
}
