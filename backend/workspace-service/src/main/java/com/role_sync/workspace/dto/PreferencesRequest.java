package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.util.Map;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class PreferencesRequest {

    private String theme;
    private String language;
    private String timezone;

    @JsonProperty("dashboard_layout")
    private Map<String, Object> dashboardLayout;
}
