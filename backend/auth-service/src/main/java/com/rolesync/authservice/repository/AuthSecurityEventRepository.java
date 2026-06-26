package com.rolesync.authservice.repository;

import com.rolesync.authservice.models.AuthSecurityEvent;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.UUID;

@Repository
public interface AuthSecurityEventRepository extends JpaRepository<AuthSecurityEvent, UUID> {

}
