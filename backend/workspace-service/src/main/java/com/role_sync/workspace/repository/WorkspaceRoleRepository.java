package com.role_sync.workspace.repository;

import com.role_sync.workspace.models.WorkspaceRole;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface WorkspaceRoleRepository extends JpaRepository<WorkspaceRole, UUID> {
    Optional<WorkspaceRole> findByRoleName(String roleName);
}
