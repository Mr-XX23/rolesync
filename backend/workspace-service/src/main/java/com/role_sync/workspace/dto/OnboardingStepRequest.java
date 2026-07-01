package com.role_sync.workspace.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class OnboardingStepRequest {

    @JsonProperty("current_step")
    private String currentStep;

    @JsonProperty("completed_steps")
    private List<String> completedSteps;

    @JsonProperty("is_completed")
    private Boolean isCompleted;
}
