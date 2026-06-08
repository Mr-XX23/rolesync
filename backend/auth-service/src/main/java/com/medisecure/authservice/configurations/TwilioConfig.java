package com.medisecure.authservice.configurations;

import com.twilio.Twilio;
import com.twilio.http.TwilioRestClient;
import jakarta.annotation.PostConstruct;
import lombok.Getter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.retry.annotation.EnableRetry;
import org.springframework.scheduling.annotation.EnableAsync;

@Configuration
@EnableAsync
@EnableRetry
@Slf4j
public class TwilioConfig {

    @Value("${twilio.account.sid}")
    private String accountSid;

    @Value("${twilio.auth.token}")
    private String authToken;

    @Getter
    @Value("${twilio.phone.number}")
    private String fromPhoneNumber;

    @PostConstruct
    public void initTwilio() {
        try {
            Twilio.init(accountSid, authToken);
            log.info("Twilio client initialized successfully");
        } catch (Exception e) {
            log.error("Failed to initialize Twilio client", e);
            throw new RuntimeException("Twilio initialization failed", e);
        }
    }

    @Bean
    public TwilioRestClient twilioRestClient() {
        return new TwilioRestClient.Builder(accountSid, authToken).build();
    }

}
