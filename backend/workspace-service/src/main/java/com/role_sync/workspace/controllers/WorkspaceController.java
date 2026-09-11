package com.role_sync.workspace.controllers;

import com.role_sync.workspace.dto.AddMemberRequest;
import com.role_sync.workspace.dto.UpdateMemberRoleRequest;
import com.role_sync.workspace.dto.WorkspaceMembershipResponse;
import com.role_sync.workspace.dto.WorkspaceRequest;
import com.role_sync.workspace.dto.WorkspaceResponse;
import com.role_sync.workspace.services.WorkspaceService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1/workspaces")
@RequiredArgsConstructor
public class WorkspaceController {

    private final WorkspaceService workspaceService;

    @PostMapping
    public Mono<ResponseEntity<WorkspaceResponse>> createWorkspace(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody WorkspaceRequest request) {

        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceService.createWorkspace(authUserId, request)
                .map(workspace -> ResponseEntity.status(HttpStatus.CREATED).body(workspace));
    }

    @GetMapping
    public Flux<WorkspaceResponse> getWorkspaces(
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader) {

        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceService.getWorkspacesForUser(authUserId);
    }

    @PostMapping("/{workspaceId}/members")
    public Mono<ResponseEntity<Map<String, Object>>> addMember(
            @PathVariable UUID workspaceId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody AddMemberRequest request) {

        UUID callerAuthUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceService.addMemberToWorkspace(workspaceId, callerAuthUserId, request)
                .map(membershipId -> ResponseEntity.status(HttpStatus.CREATED)
                        .body(Map.of(
                                "membership_id", membershipId,
                                "message", "Member added to workspace successfully"
                        )));
    }

    @PutMapping("/{workspaceId}/members/{membershipId}/role")
    public Mono<ResponseEntity<WorkspaceMembershipResponse>> updateMemberRole(
            @PathVariable UUID workspaceId,
            @PathVariable UUID membershipId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody UpdateMemberRoleRequest request) {

        UUID callerAuthUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceService.updateMemberRole(workspaceId, membershipId, callerAuthUserId, request)
                .map(ResponseEntity::ok);
    }

    @PutMapping("/{workspaceId}")
    public Mono<ResponseEntity<WorkspaceResponse>> updateWorkspace(
            @PathVariable UUID workspaceId,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader,
            @RequestHeader(value = "X-Auth-User-Id", required = false) String authUserIdHeader,
            @Valid @RequestBody WorkspaceRequest request) {

        UUID authUserId = resolveAuthUserId(userIdHeader, authUserIdHeader);
        return workspaceService.updateWorkspace(workspaceId, authUserId, request)
                .map(ResponseEntity::ok);
    }

    private UUID resolveAuthUserId(String userIdHeader, String authUserIdHeader) {
        String idStr = userIdHeader != null ? userIdHeader : authUserIdHeader;
        if (idStr == null || idStr.isBlank()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED,
                    "Missing user identification header (X-User-Id or X-Auth-User-Id)");
        }
        try {
            return UUID.fromString(idStr);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Invalid UUID format in user identification header");
        }
    }
}
