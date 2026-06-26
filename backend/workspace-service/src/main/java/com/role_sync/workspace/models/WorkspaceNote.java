package com.role_sync.workspace.models;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import lombok.AllArgsConstructor;
import lombok.Builder;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "workspace_notes")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class WorkspaceNote {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    @Column(name = "note_id")
    private UUID noteId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "workspace_id", nullable = false)
    private Workspace workspace;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "context_id", nullable = false)
    private WorkspaceContext context;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "author_profile_id", nullable = false)
    private WorkspaceProfile author;

    @Column(name = "note_title", length = 150, nullable = false)
    private String noteTitle;

    @Column(name = "note_body", columnDefinition = "TEXT")
    private String noteBody;

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
        updatedAt = LocalDateTime.now();
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
