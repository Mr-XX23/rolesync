package com.role_sync.workspace.services;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.Objects;
import java.util.UUID;

/**
 * Visibility and write rules for workspace contexts, including those written by AI agents.
 *
 * <p>Contexts whose type starts with {@code AGENT_} (e.g. a sales-agent chat session) are
 * private to the member who started them: other members get 404, as if the context did not
 * exist. Other contexts are visible to every active member. Writes additionally exclude
 * VIEWERs, and a shared context's tasks may only be changed by its creator or an OWNER/ADMIN.
 * Workspace membership itself is checked separately by {@link WorkspaceAuthorizationService}.
 */
public final class AgentContextAccess {

    public static final String PRIVATE_TYPE_PREFIX = "AGENT_";

    private AgentContextAccess() {
    }

    public static boolean isPrivate(String contextType) {
        return contextType != null && contextType.trim().toUpperCase().startsWith(PRIVATE_TYPE_PREFIX);
    }

    /** Throws 404 unless the caller may see this context. */
    public static void requireAccess(String contextType, UUID createdByProfileId, UUID callerProfileId) {
        if (isPrivate(contextType) && !Objects.equals(createdByProfileId, callerProfileId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace context not found");
        }
    }

    /**
     * Throws unless the caller may write to this context: never a VIEWER (403); a private
     * context only by its creator (404); and when {@code creatorOrAdminOnShared} is set, a
     * shared context only by its creator or an OWNER/ADMIN (403).
     */
    public static void requireWriteAccess(String contextType, UUID createdByProfileId, UUID callerProfileId,
                                          String callerRole, boolean creatorOrAdminOnShared) {
        requireWriter(callerRole);
        requireAccess(contextType, createdByProfileId, callerProfileId);
        boolean creator = Objects.equals(createdByProfileId, callerProfileId);
        boolean admin = callerRole != null && WorkspaceAuthorizationService.ADMIN_ROLES.contains(callerRole);
        if (creatorOrAdminOnShared && !isPrivate(contextType) && !creator && !admin) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "Only the context's creator or a workspace OWNER/ADMIN can change its tasks");
        }
    }

    /** Throws 403 for members who may only read. */
    public static void requireWriter(String callerRole) {
        if ("VIEWER".equals(callerRole)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Viewers cannot modify workspace records");
        }
    }
}
