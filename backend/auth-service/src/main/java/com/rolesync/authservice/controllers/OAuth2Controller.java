package com.medisecure.authservice.controllers;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth/oauth2")
public class OAuth2Controller {

    // OAuth2 endpoints are currently disabled
    // Uncomment and add OAuth2Service dependency when ready to enable

    // @GetMapping("/callback/google")
    // public ResponseEntity<OAuth2LoginResponse> googleCallback(
    // @AuthenticationPrincipal OAuth2User oauth2User,
    // HttpServletResponse response,
    // HttpServletRequest request) {
    //
    // OAuth2LoginResponse loginResponse = oauth2Service.processOAuth2Login(
    // oauth2User, response, request);
    //
    // return ResponseEntity.ok(loginResponse);
    // }
}
