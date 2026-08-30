package com.role_sync.workspace.configurations;

import com.cloudinary.Cloudinary;
import com.cloudinary.utils.ObjectUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Map;

@Configuration
public class CloudinaryConfig {

    @Value("${CLOUDINARY_CLOUD_NAME:${cloudinary.cloud-name:dkmhskfmq}}")
    private String cloudName;

    @Value("${CLOUDINARY_API_KEY:${cloudinary.api-key:577969355822157}}")
    private String apiKey;

    @Value("${CLOUDINARY_API_SECRET:${cloudinary.api-secret:cOiy0fxAXzhEijV5kgMZhi5x}}")
    private String apiSecret;

    @Bean
    public Cloudinary cloudinary() {
        String cleanCloudName = cloudName != null ? cloudName.trim().replaceAll("[\"'\r\n]", "") : "";
        String cleanApiKey = apiKey != null ? apiKey.trim().replaceAll("[\"'\r\n]", "") : "";
        String cleanApiSecret = apiSecret != null ? apiSecret.trim().replaceAll("[\"'\r\n]", "") : "";

        Map<String, String> config = ObjectUtils.asMap(
                "cloud_name", cleanCloudName,
                "api_key", cleanApiKey,
                "api_secret", cleanApiSecret,
                "secure", true
        );
        return new Cloudinary(config);
    }
}
