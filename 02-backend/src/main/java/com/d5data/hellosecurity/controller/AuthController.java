package com.d5data.hellosecurity.controller;

import com.d5data.hellosecurity.dto.LoginRequest;
import com.d5data.hellosecurity.dto.LoginResponse;
import com.d5data.hellosecurity.security.JwtService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Username/password login endpoint.
 *
 * <p>The credential check is delegated to {@link AuthenticationManager}, so the configured
 * {@code DaoAuthenticationProvider} performs the BCrypt comparison - no plaintext equality test here.</p>
 */
@RestController
@RequestMapping("/api")
public class AuthController {

    private final AuthenticationManager authenticationManager;
    private final JwtService jwtService;

    public AuthController(AuthenticationManager authenticationManager, JwtService jwtService) {
        this.authenticationManager = authenticationManager;
        this.jwtService = jwtService;
    }

    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody LoginRequest request) {
        try {
            Authentication authentication = authenticationManager.authenticate(
                    new UsernamePasswordAuthenticationToken(request.username(), request.password()));

            String token = jwtService.generateToken(authentication.getName());
            return ResponseEntity.ok(new LoginResponse(token, "Bearer", jwtService.getExpirationMs()));
        } catch (AuthenticationException ex) {
            // Wrong username or password: 401 with a generic message (no user enumeration).
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", HttpStatus.UNAUTHORIZED.value());
            body.put("error", "Unauthorized");
            body.put("message", "Invalid username or password");
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(body);
        }
    }
}
