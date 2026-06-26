package com.medisecure.authservice.aspects;

import com.github.benmanes.caffeine.cache.Cache;
import com.medisecure.authservice.annotations.RateLimited;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Aspect for enforcing rate limiting on endpoints annotated with @RateLimited.
 * Uses IP-based rate limiting with sliding window algorithm.
 */
@Aspect
@Component
@RequiredArgsConstructor
@Slf4j
public class RateLimitAspect {

    private final Cache<String, RateLimitBucket> rateLimitCache;

    @Around("@annotation(rateLimited)")
    public Object rateLimit(ProceedingJoinPoint joinPoint, RateLimited rateLimited) throws Throwable {
        ServletRequestAttributes attributes = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();

        if (attributes == null) {
            log.warn("No request attributes found for rate limiting");
            return joinPoint.proceed();
        }

        HttpServletRequest request = attributes.getRequest();
        String clientIp = getClientIp(request);
        String endpoint = request.getRequestURI();
        String rateLimitKey = buildRateLimitKey(clientIp, endpoint, rateLimited.key());

        RateLimitBucket bucket = rateLimitCache.get(rateLimitKey,
                k -> new RateLimitBucket(rateLimited.maxRequests(), rateLimited.windowSeconds()));

        if (bucket == null) {
            bucket = new RateLimitBucket(rateLimited.maxRequests(), rateLimited.windowSeconds());
            rateLimitCache.put(rateLimitKey, bucket);
        }

        if (!bucket.tryConsume()) {
            log.warn("Rate limit exceeded for IP: {} on endpoint: {} ({}  requests/{} sec)",
                    clientIp, endpoint, rateLimited.maxRequests(), rateLimited.windowSeconds());

            // Return 429 Too Many Requests
            return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS)
                    .body(Map.of(
                            "success", false,
                            "message", rateLimited.message(),
                            "retryAfter", bucket.getRetryAfterSeconds()));
        }

        return joinPoint.proceed();
    }

    private String buildRateLimitKey(String clientIp, String endpoint, String customKey) {
        if (customKey != null && !customKey.isEmpty()) {
            return String.format("rate_limit:%s:%s:%s", clientIp, endpoint, customKey);
        }
        return String.format("rate_limit:%s:%s", clientIp, endpoint);
    }

    private String getClientIp(HttpServletRequest request) {
        String ip = request.getHeader("X-Forwarded-For");
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("X-Real-IP");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getRemoteAddr();
        }
        // Handle multiple IPs (take first one)
        if (ip != null && ip.contains(",")) {
            ip = ip.split(",")[0].trim();
        }
        return ip != null ? ip : "unknown";
    }

    /**
     * Rate limit bucket using sliding window algorithm.
     */
    public static class RateLimitBucket {
        private final int maxRequests;
        private final int windowSeconds;
        private final AtomicInteger requestCount;
        private volatile LocalDateTime windowStart;

        public RateLimitBucket(int maxRequests, int windowSeconds) {
            this.maxRequests = maxRequests;
            this.windowSeconds = windowSeconds;
            this.requestCount = new AtomicInteger(0);
            this.windowStart = LocalDateTime.now();
        }

        public synchronized boolean tryConsume() {
            LocalDateTime now = LocalDateTime.now();

            // Reset window if expired
            if (now.isAfter(windowStart.plusSeconds(windowSeconds))) {
                windowStart = now;
                requestCount.set(0);
            }

            int current = requestCount.incrementAndGet();
            return current <= maxRequests;
        }

        public long getRetryAfterSeconds() {
            LocalDateTime windowEnd = windowStart.plusSeconds(windowSeconds);
            LocalDateTime now = LocalDateTime.now();
            return java.time.Duration.between(now, windowEnd).getSeconds();
        }
    }
}
