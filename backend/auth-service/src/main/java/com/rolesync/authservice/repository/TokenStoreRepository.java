package com.medisecure.authservice.repository;

import com.medisecure.authservice.models.TokenStore;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public interface TokenStoreRepository extends JpaRepository<TokenStore, UUID> {

        Optional<TokenStore> findByTokenStringAndRevokedFalse(String refreshToken);

        /**
         * Efficiently revoke all active tokens for a user with single UPDATE query.
         */
        @Modifying
        @Query("UPDATE TokenStore t SET t.revoked = true " +
                        "WHERE t.authUser.authUserId = :userId AND t.revoked = false")
        int revokeAllByUserId(@Param("userId") UUID userId);

        /**
         * Efficiently revoke all active tokens for a user by type.
         */
        @Modifying
        @Query("UPDATE TokenStore t SET t.revoked = true " +
                        "WHERE t.authUser.authUserId = :userId " +
                        "AND t.tokenType = :tokenType " +
                        "AND t.revoked = false")
        int revokeAllByUserIdAndType(
                        @Param("userId") UUID userId,
                        @Param("tokenType") String tokenType);
}
