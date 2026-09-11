package com.role_sync.workspace.services;

import com.role_sync.workspace.services.WorkspaceAuthorizationService.CallerContext;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Offline unit tests for the role-escalation rules — the security-critical part
 * of member management. {@code validateAssignableRole} and the CallerContext
 * checks are pure, so no repositories/DB are needed (repos passed as null).
 */
class WorkspaceAuthorizationServiceTest {

    private final WorkspaceAuthorizationService authz =
            new WorkspaceAuthorizationService(null, null);

    private static CallerContext caller(String role) {
        return new CallerContext(UUID.randomUUID(), role);
    }

    @Test
    void ownerRoleIsRecognized() {
        assertTrue(caller("OWNER").isOwner());
        assertTrue(caller("OWNER").isAdmin());
    }

    @Test
    void adminIsAdminButNotOwner() {
        assertTrue(caller("ADMIN").isAdmin());
        assertFalse(caller("ADMIN").isOwner());
    }

    @Test
    void memberIsNeitherAdminNorOwner() {
        assertFalse(caller("MEMBER").isAdmin());
        assertFalse(caller("MEMBER").isOwner());
    }

    @Test
    void blankOrNullRoleDefaultsToMember() {
        assertEquals("MEMBER", authz.validateAssignableRole(null, caller("OWNER")));
        assertEquals("MEMBER", authz.validateAssignableRole("  ", caller("OWNER")));
    }

    @Test
    void roleNamesAreNormalizedAndAllowed() {
        assertEquals("MEMBER", authz.validateAssignableRole("member", caller("ADMIN")));
        assertEquals("VIEWER", authz.validateAssignableRole(" Viewer ", caller("ADMIN")));
    }

    @Test
    void ownerRoleCannotBeAssignedThroughMemberOps() {
        ResponseStatusException ex = assertThrows(ResponseStatusException.class,
                () -> authz.validateAssignableRole("OWNER", caller("OWNER")));
        assertEquals(HttpStatus.BAD_REQUEST, ex.getStatusCode());
    }

    @Test
    void unknownRoleIsRejected() {
        ResponseStatusException ex = assertThrows(ResponseStatusException.class,
                () -> authz.validateAssignableRole("SUPERUSER", caller("OWNER")));
        assertEquals(HttpStatus.BAD_REQUEST, ex.getStatusCode());
    }

    @Test
    void onlyOwnerMayGrantAdmin() {
        // Owner can grant ADMIN
        assertEquals("ADMIN", authz.validateAssignableRole("ADMIN", caller("OWNER")));
        // A non-owner ADMIN cannot mint more admins
        ResponseStatusException ex = assertThrows(ResponseStatusException.class,
                () -> authz.validateAssignableRole("ADMIN", caller("ADMIN")));
        assertEquals(HttpStatus.FORBIDDEN, ex.getStatusCode());
    }
}
