package com.medisecure.authservice.annotations;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Annotation for rate limiting endpoints.
 * Uses IP-based rate limiting with configurable limits.
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface RateLimited {

    /**
     * Maximum number of requests allowed within the time window
     */
    int maxRequests() default 5;

    /**
     * Time window in seconds
     */
    int windowSeconds() default 60;

    /**
     * Custom key suffix for different rate limit buckets
     * Useful for having different limits on different endpoints
     */
    String key() default "";

    /**
     * Error message to return when rate limit is exceeded
     */
    String message() default "Too many requests. Please try again later.";
}
