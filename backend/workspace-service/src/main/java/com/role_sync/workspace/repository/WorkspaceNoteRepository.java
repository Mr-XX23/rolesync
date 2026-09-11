package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceNote;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.UUID;

@Repository
public interface WorkspaceNoteRepository extends JpaRepository<WorkspaceNote, UUID> {
    List<WorkspaceNote> findByWorkspaceWorkspaceId(UUID workspaceId);
    List<WorkspaceNote> findByContextContextId(UUID contextId);
    List<WorkspaceNote> findByContextContextIdOrderByCreatedAtAsc(UUID contextId);

    /**
     * Idempotent create-or-update keyed by a caller-chosen id; an existing id is only updated
     * when it belongs to the same context and author. Returns 0 when it belongs to another record.
     */
    @Modifying
    @Transactional
    @Query(value = "INSERT INTO workspace_notes (note_id, workspace_id, context_id, author_profile_id, note_title, "
            + "note_body, created_at, updated_at) "
            + "VALUES (:noteId, :workspaceId, :contextId, :authorId, :noteTitle, :noteBody, now(), now()) "
            + "ON CONFLICT (note_id) DO UPDATE SET note_title = EXCLUDED.note_title, "
            + "note_body = EXCLUDED.note_body, updated_at = now() "
            + "WHERE workspace_notes.context_id = EXCLUDED.context_id "
            + "AND workspace_notes.author_profile_id = EXCLUDED.author_profile_id",
            nativeQuery = true)
    int upsert(@Param("noteId") UUID noteId, @Param("workspaceId") UUID workspaceId,
               @Param("contextId") UUID contextId, @Param("authorId") UUID authorId,
               @Param("noteTitle") String noteTitle, @Param("noteBody") String noteBody);
}
