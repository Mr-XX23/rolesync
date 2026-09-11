package com.role_sync.workspace.services;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Offline tests for the agent-context visibility rule (pure logic, no repositories). */
class AgentContextAccessTest {

    private final UUID creator = UUID.randomUUID();
    private final UUID colleague = UUID.randomUUID();

    @Test
    void agentContextsArePrivateToTheirCreator() {
        assertDoesNotThrow(() -> AgentContextAccess.requireAccess("AGENT_SESSION", creator, creator));
        ResponseStatusException denied = assertThrows(ResponseStatusException.class,
                () -> AgentContextAccess.requireAccess("AGENT_SESSION", creator, colleague));
        // 404, not 403: other members cannot even learn the context exists.
        assertEquals(HttpStatus.NOT_FOUND, denied.getStatusCode());
    }

    @Test
    void privacyMatchesTheAgentPrefixCaseInsensitively() {
        assertTrue(AgentContextAccess.isPrivate("AGENT_GOAL"));
        assertTrue(AgentContextAccess.isPrivate(" agent_session "));
        assertFalse(AgentContextAccess.isPrivate("DEAL"));
        assertFalse(AgentContextAccess.isPrivate(null));
    }

    @Test
    void otherContextsStayVisibleToEveryMember() {
        assertDoesNotThrow(() -> AgentContextAccess.requireAccess("DEAL", creator, colleague));
        assertDoesNotThrow(() -> AgentContextAccess.requireAccess(null, creator, colleague));
    }

    @Test
    void viewersCannotWriteAnywhere() {
        ResponseStatusException denied = assertThrows(ResponseStatusException.class,
                () -> AgentContextAccess.requireWriteAccess("DEAL", creator, creator, "VIEWER", false));
        assertEquals(HttpStatus.FORBIDDEN, denied.getStatusCode());
    }

    @Test
    void onlyTheCreatorWritesToAPrivateAgentContext() {
        assertDoesNotThrow(() -> AgentContextAccess.requireWriteAccess("AGENT_SESSION", creator, creator, "MEMBER", true));
        ResponseStatusException denied = assertThrows(ResponseStatusException.class,
                () -> AgentContextAccess.requireWriteAccess("AGENT_SESSION", creator, colleague, "OWNER", true));
        assertEquals(HttpStatus.NOT_FOUND, denied.getStatusCode()); // even an owner can't see into it
    }

    @Test
    void sharedContextTasksAreChangedOnlyByTheCreatorOrAnAdmin() {
        assertDoesNotThrow(() -> AgentContextAccess.requireWriteAccess("DEAL", creator, creator, "MEMBER", true));
        assertDoesNotThrow(() -> AgentContextAccess.requireWriteAccess("DEAL", creator, colleague, "ADMIN", true));
        assertDoesNotThrow(() -> AgentContextAccess.requireWriteAccess("DEAL", creator, colleague, "OWNER", true));
        ResponseStatusException denied = assertThrows(ResponseStatusException.class,
                () -> AgentContextAccess.requireWriteAccess("DEAL", creator, colleague, "MEMBER", true));
        assertEquals(HttpStatus.FORBIDDEN, denied.getStatusCode());
        // Notes on a shared context: any writer (the note upsert itself only updates the author's own notes).
        assertDoesNotThrow(() -> AgentContextAccess.requireWriteAccess("DEAL", creator, colleague, "MEMBER", false));
    }
}
