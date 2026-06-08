package com.medisecure.authservice.configurations;


import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConfigurationProperties(prefix = "security")
@Getter
@Setter
public class PublicEndpointsConfig {
    private String[] publicEndpoints;
}
