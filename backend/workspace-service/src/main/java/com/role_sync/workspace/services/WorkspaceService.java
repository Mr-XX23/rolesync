package com.role_sync.workspace.services;

import com.role_sync.workspace.dto.AddMemberRequest;
import com.role_sync.workspace.dto.UpdateMemberRoleRequest;
import com.role_sync.workspace.dto.WorkspaceRequest;
import com.role_sync.workspace.models.Workspace;
import com.role_sync.workspace.models.WorkspaceMembership;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.UUID;

public interface WorkspaceService {
    Mono<Workspace> createWorkspace(UUID authUserId, WorkspaceRequest request);
    Flux<Workspace> getWorkspacesForUser(UUID authUserId);
    Mono<UUID> addMemberToWorkspace(UUID workspaceId, AddMemberRequest request);
    Mono<WorkspaceMembership> updateMemberRole(UUID workspaceId, UUID membershipId, UpdateMemberRoleRequest request);
}
