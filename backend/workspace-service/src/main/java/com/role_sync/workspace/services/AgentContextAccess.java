package com.role_sync.workspace.services;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.Objects;
import java.util.UUID;

/**
 * Visibility rule for contexts written by AI agents.
 *
 * <p>Contexts whose type starts with {@code AGENT_} (e.g. a sales-agent chat session) are
 * private to the member who started them: other members of the workspace get 404, as if
 * the context did not exist. Other contexts stay visible to every active member.
 * Workspace membership itself is checked separately by {@link WorkspaceAuthorizationService}.
 */
public final class AgentContextAccess {

    public static final String PRIVATE_TYPE_PREFIX = "AGENT_";

    private AgentContextAccess() {
    }

    public static boolean isPrivate(String contextType) {
        return contextType != null && contextType.trim().toUpperCase().startsWith(PRIVATE_TYPE_PREFIX);
    }

    /** Throws 404 unless the caller may see (and write to) this context. */
    public static void requireAccess(String contextType, UUID createdByProfileId, UUID callerProfileId) {
        if (isPrivate(contextType) && !Objects.equals(createdByProfileId, callerProfileId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Workspace context not found");
        }
    }
}
