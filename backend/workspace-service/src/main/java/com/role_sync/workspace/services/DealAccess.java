package com.role_sync.workspace.services;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Rules for workspace deals. Deals are shared by the workspace: every active member can see
 * them, every member except VIEWERs can create and edit them, and only a deal's owner or a
 * workspace OWNER/ADMIN can delete one. Membership itself is checked by
 * {@link WorkspaceAuthorizationService}.
 */
public final class DealAccess {

    /** Pipeline order. */
    public static final List<String> STAGES = List.of("PROSPECTING", "QUALIFIED", "PROPOSAL", "NEGOTIATION", "WON", "LOST");
    public static final Set<String> CLOSED_STAGES = Set.of("WON", "LOST");

    private DealAccess() {
    }

    public static String normalizeStage(String stage) {
        String normalized = stage == null ? "" : stage.trim().toUpperCase(Locale.ROOT);
        if (!STAGES.contains(normalized)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unknown deal stage '" + stage + "'");
        }
        return normalized;
    }

    /** Refuses a write that was prepared against a version someone has since changed. */
    public static void requireExpectedVersion(Long expected, Long current) {
        if (expected != null && !Objects.equals(expected, current)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "This deal was changed by someone else (now version " + current + "); reload it and try again");
        }
    }

    public static boolean canDelete(UUID ownerProfileId, UUID callerProfileId, String callerRole) {
        boolean admin = callerRole != null && WorkspaceAuthorizationService.ADMIN_ROLES.contains(callerRole);
        return admin || Objects.equals(ownerProfileId, callerProfileId);
    }

    public static void requireCanDelete(UUID ownerProfileId, UUID callerProfileId, String callerRole) {
        AgentContextAccess.requireWriter(callerRole);
        if (!canDelete(ownerProfileId, callerProfileId, callerRole)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "Only the deal's owner or a workspace OWNER/ADMIN can delete it");
        }
    }

    /** When the deal closed: set on reaching WON/LOST, kept while it stays closed, cleared if reopened. */
    public static LocalDateTime closedAt(String previousStage, String newStage, LocalDateTime previousClosedAt,
                                         LocalDateTime now) {
        if (!CLOSED_STAGES.contains(newStage)) {
            return null;
        }
        boolean wasClosed = previousStage != null && CLOSED_STAGES.contains(previousStage);
        return wasClosed && previousClosedAt != null ? previousClosedAt : now;
    }
}
