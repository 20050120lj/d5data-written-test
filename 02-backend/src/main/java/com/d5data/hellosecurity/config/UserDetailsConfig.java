package com.d5data.hellosecurity.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;

/**
 * Credential storage and password hashing.
 *
 * <p>Kept separate from {@link SecurityConfig} on purpose: {@code JwtAuthenticationFilter} needs the
 * {@link UserDetailsService}, and {@code SecurityConfig} needs the filter. Putting both in one class
 * would create a circular bean reference, which Spring Boot 2.6+ rejects by default.</p>
 */
@Configuration
public class UserDetailsConfig {

    /**
     * BCrypt with the default strength (10). Each call produces a fresh salted hash, so the same raw
     * password never maps to the same stored value.
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    /**
     * Single demo account required by the task: username {@code test} / password {@code 123456}.
     * The plaintext value exists only in this source line; the container stores the BCrypt hash.
     */
    @Bean
    public UserDetailsService userDetailsService(PasswordEncoder passwordEncoder) {
        UserDetails user = User.withUsername("test")
                .password(passwordEncoder.encode("123456"))
                .roles("USER")
                .build();
        return new InMemoryUserDetailsManager(user);
    }

    /**
     * Exposes the {@code DaoAuthenticationProvider} chain that verifies the login request.
     */
    @Bean
    public AuthenticationManager authenticationManager(AuthenticationConfiguration configuration) throws Exception {
        return configuration.getAuthenticationManager();
    }
}
