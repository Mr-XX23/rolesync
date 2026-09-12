package com.role_sync.workspace.services;

import com.role_sync.workspace.models.WorkspaceProfile;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DealAccessTest {

    private final UUID owner = UUID.randomUUID();
    private final UUID other = UUID.randomUUID();

    @Test
    void stagesAreNormalizedAndUnknownOnesRefused() {
        assertEquals("NEGOTIATION", DealAccess.normalizeStage(" negotiation "));
        ResponseStatusException refused = assertThrows(ResponseStatusException.class, () -> DealAccess.normalizeStage("CLOSED"));
        assertEquals(HttpStatus.BAD_REQUEST, refused.getStatusCode());
    }

    @Test
    void aStaleVersionIsAConflictAndNoVersionMeansLastWriteWins() {
        assertDoesNotThrow(() -> DealAccess.requireExpectedVersion(null, 7L));
        assertDoesNotThrow(() -> DealAccess.requireExpectedVersion(7L, 7L));
        ResponseStatusException stale = assertThrows(ResponseStatusException.class, () -> DealAccess.requireExpectedVersion(6L, 7L));
        assertEquals(HttpStatus.CONFLICT, stale.getStatusCode());
    }

    @Test
    void onlyTheOwnerOrAnAdminCanDelete() {
        assertTrue(DealAccess.canDelete(owner, owner, "MEMBER"));
        assertTrue(DealAccess.canDelete(owner, other, "ADMIN"));
        assertTrue(DealAccess.canDelete(owner, other, "OWNER"));
        assertFalse(DealAccess.canDelete(owner, other, "MEMBER"));
        ResponseStatusException memberRefused = assertThrows(ResponseStatusException.class,
                () -> DealAccess.requireCanDelete(owner, other, "MEMBER"));
        assertEquals(HttpStatus.FORBIDDEN, memberRefused.getStatusCode());
    }

    @Test
    void viewersCannotDeleteEvenTheirOwnDeals() {
        ResponseStatusException refused = assertThrows(ResponseStatusException.class,
                () -> DealAccess.requireCanDelete(owner, owner, "VIEWER"));
        assertEquals(HttpStatus.FORBIDDEN, refused.getStatusCode());
    }

    @Test
    void closingSetsClosedAtOnceAndReopeningClearsIt() {
        LocalDateTime firstClose = LocalDateTime.of(2026, 9, 1, 10, 0);
        LocalDateTime later = LocalDateTime.of(2026, 9, 5, 10, 0);
        assertEquals(firstClose, DealAccess.closedAt("NEGOTIATION", "WON", null, firstClose));
        assertEquals(firstClose, DealAccess.closedAt("WON", "LOST", firstClose, later)); // still closed: keeps the date
        assertNull(DealAccess.closedAt("WON", "NEGOTIATION", firstClose, later));
        assertNull(DealAccess.closedAt(null, "PROSPECTING", null, later));
    }

    @Test
    void ownersAreShownByDisplayNameThenFullName() {
        WorkspaceProfile named = WorkspaceProfile.builder().displayName(" Jane D. ").firstName("Jane").lastName("Doe").build();
        WorkspaceProfile unnamed = WorkspaceProfile.builder().firstName("Jane").lastName("Doe").build();
        WorkspaceProfile blank = WorkspaceProfile.builder().firstName("").lastName("").build();
        assertEquals("Jane D.", WorkspaceDealServiceImpl.displayName(named));
        assertEquals("Jane Doe", WorkspaceDealServiceImpl.displayName(unnamed));
        assertEquals("Workspace member", WorkspaceDealServiceImpl.displayName(blank));
    }
}
