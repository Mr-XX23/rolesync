package com.medisecure.authservice.configurations;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import com.medisecure.authservice.aspects.RateLimitAspect;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.TimeUnit;

/**
 * Cache configuration for high-performance user data retrieval
 * Uses Caffeine cache with TTL for frequently accessed user details
 * userStatus cache has shorter TTL (5s) to support polling during verification
 */
@Configuration
@EnableCaching
public class CacheConfig {

    @Bean
    public CacheManager cacheManager() {
        CaffeineCacheManager cacheManager = new CaffeineCacheManager();
        cacheManager.setCaffeine(caffeineCacheBuilder());
        cacheManager.setCacheNames(java.util.Arrays.asList(
                "userDetails",
                "userDetailsById",
                "userStatus"));
        return cacheManager;
    }

    /**
     * Caffeine cache configuration with TTL
     * Optimized for verification polling with 5-second TTL for userStatus
     */
    private Caffeine<Object, Object> caffeineCacheBuilder() {
        return Caffeine.newBuilder()
                .expireAfterWrite(5, TimeUnit.SECONDS) // 5 second TTL for userStatus
                .maximumSize(10000) // Max 10k cached entries
                .recordStats(); // Enable cache statistics for monitoring
    }

    /**
     * Rate limiting cache with 60-second TTL.
     * Stores rate limit buckets for IP-based rate limiting.
     */
    @Bean
    public Cache<String, RateLimitAspect.RateLimitBucket> rateLimitCache() {
        return Caffeine.newBuilder()
                .expireAfterWrite(60, TimeUnit.SECONDS) // Match rate limit window
                .maximumSize(50000) // Support more concurrent users
                .recordStats()
                .build();
    }
}
