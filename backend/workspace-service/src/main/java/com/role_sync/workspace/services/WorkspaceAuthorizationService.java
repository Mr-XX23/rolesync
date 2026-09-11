package com.role_sync.workspace.services;

import com.role_sync.workspace.models.WorkspaceProfile;
import com.role_sync.workspace.repository.WorkspaceMembershipRepository;
import com.role_sync.workspace.repository.WorkspaceProfileRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.Set;
import java.util.UUID;

/**
 * Central authorization for workspace operations.
 *
 * <p>Identity ({@code authUserId}) is supplied by the gateway via the verified
 * {@code X-User-Id} header — see the gateway edge filter. This service answers
 * "is this caller allowed to act on this workspace?" using ID-only projection
 * queries (resolved as SQL joins), never lazy-proxy navigation, so it is safe
 * in this WebFlux + blocking-JPA service where no session is open outside a
 * repository call.
 */
@Service
@RequiredArgsConstructor
public class WorkspaceAuthorizationService {

    private final WorkspaceProfileRepository workspaceProfileRepository;
    private final WorkspaceMembershipRepository workspaceMembershipRepository;

    /** Roles a caller may assign to another member. OWNER is never assignable here. */
    public static final Set<String> ASSIGNABLE_ROLES = Set.of("ADMIN", "MEMBER", "VIEWER");
    /** Roles permitted to manage members and mutate the workspace. */
    public static final Set<String> ADMIN_ROLES = Set.of("OWNER", "ADMIN");

    /** Resolved caller identity within a workspace. */
    public record CallerContext(UUID profileId, String roleName) {
        public boolean isAdmin() {
            return roleName != null && ADMIN_ROLES.contains(roleName);
        }

        public boolean isOwner() {
            return "OWNER".equals(roleName);
        }
    }

    /** The caller's workspace profile, or 403 if none exists. */
    public WorkspaceProfile requireProfile(UUID authUserId) {
        if (authUserId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Authentication required");
        }
        return workspaceProfileRepository.findByAuthUserId(authUserId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.FORBIDDEN,
                        "No workspace profile exists for the authenticated user"));
    }

    /** Requires the caller to be an active member of the workspace; returns their context. */
    public CallerContext requireActiveMembership(UUID authUserId, UUID workspaceId) {
        WorkspaceProfile profile = requireProfile(authUserId);
        String roleName = workspaceMembershipRepository
                .findActiveRoleName(workspaceId, profile.getProfileId())
                .map(WorkspaceAuthorizationService::normalizeRole)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.FORBIDDEN,
                        "You are not an active member of this workspace"));
        return new CallerContext(profile.getProfileId(), roleName);
    }

    /** As {@link #requireActiveMembership} but the caller must be OWNER or ADMIN. */
    public CallerContext requireAdmin(UUID authUserId, UUID workspaceId) {
        CallerContext caller = requireActiveMembership(authUserId, workspaceId);
        if (!caller.isAdmin()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "This action requires OWNER or ADMIN role in the workspace");
        }
        return caller;
    }

    /**
     * Validates and normalizes a role a caller wants to assign to another member.
     * Rejects unknown roles and OWNER (ownership is set at creation, not assigned here).
     * Granting ADMIN is restricted to the workspace OWNER.
     */
    public String validateAssignableRole(String requested, CallerContext caller) {
        String normalized = (requested == null || requested.isBlank())
                ? "MEMBER" : normalizeRole(requested);
        if (!ASSIGNABLE_ROLES.contains(normalized)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Invalid role '" + requested + "'. Allowed roles: " + ASSIGNABLE_ROLES);
        }
        if ("ADMIN".equals(normalized) && !caller.isOwner()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "Only the workspace OWNER can grant the ADMIN role");
        }
        return normalized;
    }

    private static String normalizeRole(String role) {
        return role == null ? null : role.trim().toUpperCase();
    }
}
