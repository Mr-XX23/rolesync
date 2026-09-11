package com.role_sync.workspace.services;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DefaultWorkspaceNameTest {

    @Test
    void personalWorkspacesAreNamedAfterTheOwner() {
        assertEquals("Jane's Workspace", WorkspaceServiceImpl.defaultWorkspaceName(" Jane "));
    }

    @Test
    void withoutAFirstNameTheWorkspaceIsPersonal() {
        assertEquals("Personal Workspace", WorkspaceServiceImpl.defaultWorkspaceName(""));
        assertEquals("Personal Workspace", WorkspaceServiceImpl.defaultWorkspaceName(null));
    }
}
