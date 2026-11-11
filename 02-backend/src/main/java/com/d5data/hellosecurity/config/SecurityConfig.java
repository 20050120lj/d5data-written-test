package com.d5data.hellosecurity.config;

import com.d5data.hellosecurity.security.JwtAuthenticationFilter;
import com.d5data.hellosecurity.security.RestAuthenticationEntryPoint;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * Spring Security 6 filter chain.
 *
 * <p>Spring Boot 3 removed {@code WebSecurityConfigurerAdapter}; the supported extension point is a
 * {@link SecurityFilterChain} bean, which is what this class exposes. Credential storage lives in
 * {@link UserDetailsConfig} to keep the bean graph acyclic.</p>
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    private final JwtAuthenticationFilter jwtAuthenticationFilter;
    private final RestAuthenticationEntryPoint restAuthenticationEntryPoint;

    public SecurityConfig(JwtAuthenticationFilter jwtAuthenticationFilter,
                          RestAuthenticationEntryPoint restAuthenticationEntryPoint) {
        this.jwtAuthenticationFilter = jwtAuthenticationFilter;
        this.restAuthenticationEntryPoint = restAuthenticationEntryPoint;
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                // CSRF tokens protect cookie/session based browser flows. This API carries its credential
                // in the Authorization header and keeps no session, so CSRF protection adds nothing here.
                .csrf(AbstractHttpConfigurer::disable)

                // No HttpSession is created or consulted: each request must bring its own bearer token.
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))

                // Only the login endpoint is public. Everything else, /api/hello included, requires
                // authentication - it is deliberately NOT permitted anonymously.
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(HttpMethod.POST, "/api/login").permitAll()
                        .requestMatchers("/error").permitAll()
                        .anyRequest().authenticated())

                // An unauthenticated request must be answered 401 Unauthorized. Two defaults would get this
                // wrong: formLogin() answers 302 to a login page, and a chain with no entry point falls back
                // to Http403ForbiddenEntryPoint (403). Hence the explicit JSON entry point.
                .exceptionHandling(handling -> handling.authenticationEntryPoint(restAuthenticationEntryPoint))

                // Disabled explicitly so no redirect-based or browser-prompt based flow can interfere.
                .formLogin(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)

                // Authenticate the bearer token before the authorization rules are evaluated.
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }
}
