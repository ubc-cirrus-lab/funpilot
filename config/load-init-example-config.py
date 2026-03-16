#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib import error, request
import time

from redis import Redis

# Seed the bootstrap example configuration into the public namespace.
# Public configs are readable by all users and treated as templates (read-only in API).
USER_ID = "public"
CONFIG_ID = "default-funpilot-config"
CONFIG_API_URL = "http://127.0.0.1:8082"
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 46379
REDIS_DB = 0

redis_client = Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            encoding="utf-8",
            decode_responses=True,
        )
redis_client.ping()

# Create Config
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", mapping={"created_at":time.time_ns(), "updated_at":time.time_ns()})
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", mapping={"workflow_name":"triage-propose-judge"})

# Alert rule definitions
ALERT_RULES = {
    "high-cpu-throttling-rate": {
        "display_name": "High CPU Throttling Rate",
        "description": "Average CPU throttling rate across the function's pods over the last {{.RangeVectorWindowSeconds}} seconds exceeds {{.Threshold}}.",
        "expr":  (
                    "avg(rate(container_cpu_cfs_throttled_periods_total{pod=~\"{{.RevisionName}}-.*\"}[{{.RangeVectorWindowSeconds}}s])/"
                    "rate(container_cpu_cfs_periods_total{pod=~\"{{.RevisionName}}-.*\"}[{{.RangeVectorWindowSeconds}}s]))"
                ),
        "range_vector_window_seconds": 60,
        "operator": "gt",
        "threshold": 0.1,
        "for_duration_seconds": 0,
        "repeat_interval_seconds": 60,
    },
    "high-p99-latency": {
        "display_name": "High P99 Request Latency",
        "description": "p99 request latency over the last {{.RangeVectorWindowSeconds}} seconds exceeds {{.Threshold}} ms.",
        "expr": (
                    "histogram_quantile(0.99, sum(rate(istio_request_duration_milliseconds_bucket"
                    "{destination_service_name=\"{{.RevisionName}}\"}[{{.RangeVectorWindowSeconds}}s])) by (destination_service_name, le))"
                ),
        "range_vector_window_seconds": 60,        
        "operator": "gt",
        "threshold": 250,
        "for_duration_seconds": 0,
        "repeat_interval_seconds": 60,
    },
    "low-cpu-usage": {
        "display_name": "Low CPU Usage",
        "description": "Average CPU usage (percentage of allocated CPU) across the function's pods over the last {{.RangeVectorWindowSeconds}} seconds is below {{.Threshold}}%.",
        "expr": (
                    "avg(( sum by (pod) ( rate(container_cpu_usage_seconds_total{ pod=~\"{{.RevisionName}}.*\", "
                    "container=\"user-container\"}[{{.RangeVectorWindowSeconds}}s]) ) / sum by (pod) ( kube_pod_container_resource_limits{ "
                    "pod=~\"{{.RevisionName}}.*\", container != \"POD\", resource=\"cpu\" } ) ) * 100 )"
                ),
        "range_vector_window_seconds": 60,
        "operator": "lt",
        "threshold": 10,
        "for_duration_seconds": 30,
        "repeat_interval_seconds": 60,
    },
}

# Load Alert Rules
for rule_key, rule_def in ALERT_RULES.items():
    redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", f"alert_rule:{rule_key}", json.dumps(rule_def, ensure_ascii=False))

# Metric definitions
METRIC_DEFINITIONS  = {
    "cpu-throttling-rate": {
        "display_name": "CPU Throttling Rate",
        "description": "Average CPU throttling ratio over the past {{.RangeVectorWindowSeconds}} seconds. `nan` may indicate undefined ratio (e.g., denominator=0) due to pod inactivity or churn; interpret together with pod count and request rate.",
        "unit": "rate",
        "expr": (
            """avg(rate(container_cpu_cfs_throttled_periods_total{pod=~"{{.RevisionName}}.*"}[{{.RangeVectorWindowSeconds}}s])/rate(container_cpu_cfs_periods_total{pod=~"{{.RevisionName}}.*"}[{{.RangeVectorWindowSeconds}}s]))"""
        ),
        "range_vector_window_seconds": 60,
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "concurrency": {
        "display_name": "Revision Concurrency",
        "description": "Current number of in-flight requests handled by the revision.",
        "unit": "concurrent requests",
        "expr": """kn_revision_concurrency_stable{kn_revision_name="{{.RevisionName}}"}""",
        "range_vector_window_seconds": None, # this is a gauge, no range vector needed
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "avg-request-latency": {
        "display_name": "Average Latency of Completed Requests",
        "description": "Average latency of completed successful requests in the past {{.RangeVectorWindowSeconds}} seconds for this revision. `nan` means there were no successful completions in the window, so the average is undefined (often when traffic is zero).",
        "unit": "ms",
        "expr": (
            """sum(rate(istio_request_duration_milliseconds_sum{destination_service_name="{{.RevisionName}}",response_code="200"}[{{.RangeVectorWindowSeconds}}s])) / sum(rate(istio_request_duration_milliseconds_count{destination_service_name="{{.RevisionName}}",response_code="200"}[{{.RangeVectorWindowSeconds}}s]))"""
        ),
        "range_vector_window_seconds": 30,
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "p95-request-latency": {
        "display_name": "P95 Latency of Completed Requests",
        "description": "P95 latency of completed successful requests in the past {{.RangeVectorWindowSeconds}} seconds for this revision. `nan` means there were no successful completions in the window, so the quantile is undefined (often when traffic is zero).",
        "unit": "ms",
        "expr": (
            """histogram_quantile(0.95, sum(rate(istio_request_duration_milliseconds_bucket{destination_service_name="{{.RevisionName}}",response_code="200"}[{{.RangeVectorWindowSeconds}}s])) by (destination_service_name, le))"""
        ),
        "range_vector_window_seconds": 30,
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "request-count": {
        "display_name": "Incoming Request Rate",
        "description": "Incoming request rate at the ingress, averaged over the past {{.RangeVectorWindowSeconds}} seconds for this revision.",
        "unit": "rps",
        "expr": (
            """sum(rate(wasm_http_downstream_rq{authority=~"{{.RevisionName}}.*", service="istio-ingressgateway"}[{{.RangeVectorWindowSeconds}}s]))"""
        ),
        "range_vector_window_seconds": 30,
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "pod-count": {
        "display_name": "Pod Count",
        "description": "Number of running pods of this revision (no data (nan) means 0 running pods).",
        "unit": "pods",
        "expr": """count(kube_pod_status_phase{phase="Running", pod=~"{{.RevisionName}}.*"} == 1) or vector(0)""",
        "range_vector_window_seconds": None, # this is a gauge, no range vector needed
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "cpu-utilization": {
        "display_name": "CPU Utilization",
        "description": "CPU usage rate over the past {{.RangeVectorWindowSeconds}} seconds as a percentage of configured CPU limit, averaged across pods of this revision.",
        "unit": "%",
        "expr": (
            """avg(( sum by (pod) ( rate(container_cpu_usage_seconds_total{ pod=~"{{.RevisionName}}.*", container = "user-container"}[{{.RangeVectorWindowSeconds}}s]) ) / sum by (pod) ( kube_pod_container_resource_limits{ pod=~"{{.RevisionName}}.*", container != "POD", resource="cpu" } ) ) * 100 )"""
        ),
        "range_vector_window_seconds": 60,
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "memory-utilization": {
        "display_name": "Memory Utilization",
        "description": "Current memory usage as a percentage of configured memory limit, averaged across pods of this revision.",
        "unit": "%",
        "expr": (
            """avg(( sum by (pod) ( container_memory_usage_bytes{ pod=~"{{.RevisionName}}.*", container = "user-container"} ) / sum by (pod) ( kube_pod_container_resource_limits{ pod=~"{{.RevisionName}}.*", container != "POD", resource="memory" } ) ) * 100 )"""
        ),
        "range_vector_window_seconds": None, # this is a gauge, no range vector needed
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },

    "is-panic-mode": {
        "display_name": "Panic Mode Status",
        "description": "Whether the revision is currently in panic mode (1 for yes, 0 for no).",
        "unit": "boolean",
        "expr": (
            """kn_revision_panic_mode{kn_revision_name="{{.RevisionName}}"}"""
        ),
        "range_vector_window_seconds": None, # this is a gauge, no range vector needed
        "query_window_seconds": 120,
        "query_step_seconds": 15,
    },
}
# Load Metric Definitions
for metric_key, metric_def in METRIC_DEFINITIONS.items():
    redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", f"metric_definition:{metric_key}", json.dumps(metric_def, ensure_ascii=False))

TRIAGE_SUMMARY_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "triage_summary",
        "schema": {
            "properties": {
                "triage_summary": {
                    "description": "triage summary in 6-7 sentences",
                    "title": "Triage Summary",
                    "type": "string"
                },
                "pre_stop": {
                    "anyOf": [
                        {"type": "boolean"},
                        {"type": "null"}
                    ],
                    "default": None,
                    "description": "Optional early-stop signal. If true, skip further steps.",
                    "title": "Pre Stop"
                }
            },
            "required": ["triage_summary"],
            "title": "TriageSummary",
            "type": "object",
            "additionalProperties": False
        },
        "strict": True,
    },
}

# # Example triage-propose-judge agent
WORKFLOW_TRIAGE_PROPOSE_JUDGE = {
    "name": "triage-propose-judge",
    "entry_point": "triage_llm",
    "metadata": {
        "version": "3.0",
        "description": "Full triage-propose-judge loop as a fully generic dynamic "
                       "workflow. All parsing and routing logic is handled by "
                       "registered handlers and custom routers, zero hardcoded "
                       "stage names in the engine.",
        "author": "funpilot"
    },
    "nodes": [
        {
            "name": "triage_llm",
            "node_type": "llm_call",
            "description": "Call LLM to triage incoming alerts and produce a diagnostic summary",
            "llm_call_config": {
                "prompt_template_key": "triage_node",
                "llm_client_key": "triage_node",
                "message_role": "human",
                "response_format": TRIAGE_SUMMARY_RESPONSE_FORMAT,
                "output_state_key": "_last_llm_response",
                "maintain_history": False,
            }
        },
        {
            "name": "parse_triage",
            "node_type": "tool_call",
            "description": "Parse the triage LLM response: extract summary and pre_stop signal",
            "tool_call_config": {
                "handler_name": "parse_triage_response",
                "handler_params": {}
            }
        },
        {
            "name": "propose_llm",
            "node_type": "llm_call",
            "description": "Call LLM to propose configuration changes based on triage analysis",
            "llm_call_config": {
                "prompt_template_key": "propose_node",
                "llm_client_key": "propose_node",
                "message_role": "human",
                "output_state_key": "_last_llm_response",
                "maintain_history": True,
                "history_state_key": "propose_node_messages",
                "template_selectors": [
                    {
                        "state_field": "judge_result",
                        "nested_key": "verdict",
                        "value_mapping": {
                            "REJECTED": "propose_node_rejected",
                            "NEED_METRICS": "propose_node_need_metrics"
                        }
                    },
                    {
                        "state_field": "has_fresh_additional_metrics",
                        "value_mapping": {
                            "TRUE": "propose_node_need_metrics"
                        }
                    }
                ]
            }
        },
        {
            "name": "normalize_proposal",
            "node_type": "tool_call",
            "description": "Parse and normalize the propose LLM response into proposal_json and proposed_changes",
            "tool_call_config": {
                "handler_name": "normalize_proposal",
                "handler_params": {}
            }
        },
        {
            "name": "guardrail",
            "node_type": "guardrail",
            "description": "Validate the proposed changes against safety guardrails",
            "guardrail_config": {}
        },
        {
            "name": "judge_llm",
            "node_type": "llm_call",
            "description": "Call LLM to judge the proposed changes",
            "llm_call_config": {
                "prompt_template_key": "judge_node",
                "llm_client_key": "judge_node",
                "message_role": "system",
                "output_state_key": "_last_llm_response",
                "maintain_history": False,
            }
        },
        {
            "name": "parse_judge",
            "node_type": "tool_call",
            "description": "Parse the judge LLM response: extract verdict, feedback, and handle revisions",
            "tool_call_config": {
                "handler_name": "parse_judge_response",
                "handler_params": {}
            }
        },
        {
            "name": "fetch_metrics",
            "node_type": "metrics",
            "description": "Fetch additional metrics from Thanos when requested",
            "metrics_config": {}
        }
    ],
    "edges": [
        {
            "source": "triage_llm",
            "edge_type": "direct",
            "target": "parse_triage"
        },
        {
            "source": "parse_triage",
            "edge_type": "conditional",
            "router": {
                "router_type": "custom",
                "custom_handler": "triage_router"
            },
            "routes": [
                {"label": "PROPOSE", "target": "propose_llm"},
                {"label": "PRESTOPPED", "target": "__end__"},
                {"label": "STOPPED", "target": "__end__"}
            ]
        },
        {
            "source": "propose_llm",
            "edge_type": "direct",
            "target": "normalize_proposal"
        },
        {
            "source": "normalize_proposal",
            "edge_type": "conditional",
            "router": {
                "router_type": "custom",
                "custom_handler": "propose_router"
            },
            "routes": [
                {"label": "GUARDRAIL", "target": "guardrail"},
                {"label": "NEED_METRICS", "target": "fetch_metrics"},
                {"label": "STOPPED", "target": "__end__"}
            ]
        },
        {
            "source": "guardrail",
            "edge_type": "direct",
            "target": "judge_llm"
        },
        {
            "source": "judge_llm",
            "edge_type": "direct",
            "target": "parse_judge"
        },
        {
            "source": "parse_judge",
            "edge_type": "conditional",
            "router": {
                "router_type": "custom",
                "custom_handler": "judge_router"
            },
            "routes": [
                {"label": "REJECTED", "target": "propose_llm"},
                {"label": "APPROVED", "target": "__end__"},
                {"label": "NEED_METRICS", "target": "fetch_metrics"},
                {"label": "REVISED", "target": "__end__"},
                {"label": "STOPPED", "target": "__end__"}
            ]
        },
        {
            "source": "fetch_metrics",
            "edge_type": "direct",
            "target": "propose_llm"
        }
    ]
}

# Example oneshot agent
WORKFLOW_ONESHOT = {
    "name": "oneshot",
    "entry_point": "analyze_and_propose",
    "metadata": {
        "version": "3.1",
        "description": "Single-step workflow: one LLM call directly outputs "
                       "control knob updates. No multi-step pipeline. Uses "
                       "is_final_output for inline extraction.",
        "author": "funpilot"
    },
    "nodes": [
        {
            "name": "analyze_and_propose",
            "node_type": "llm_call",
            "description": "Single LLM call that analyzes alerts and proposes "
                           "changes directly. is_final_output "
                           "parses the response and populates "
                           "final_proposed_changes inline.",
            "llm_call_config": {
                "prompt_template_key": "oneshot_node",
                "llm_client_key": "propose_node",
                "message_role": "human",
                "output_state_key": "_last_llm_response",
                "maintain_history": False,
                "is_final_output": True,
            }
        }
    ],
    "edges": [
        {
            "source": "analyze_and_propose",
            "edge_type": "direct",
            "target": "__end__"
        }
    ]
}

# Example fixed-update agent for testing
WORKFLOW_FIXED_UPDATE = {
    "name": "fixed-update",
    "entry_point": "fixed_output",
    "metadata": {
        "version": "3.1",
        "description": "Fixed-update workflow: LLM outputs a fixed CPU limit "
                       "change to 360m. Designed for testing the LLM backend "
                       "and system plumbing.",
        "author": "funpilot"
    },
    "nodes": [
        {
            "name": "fixed_output",
            "node_type": "llm_call",
            "description": "LLM call that outputs a fixed control knob update "
                           "(CPU -> 360m).",
            "llm_call_config": {
                "prompt_template_key": "fixed_update_node",
                "llm_client_key": "propose_node",
                "message_role": "human",
                "output_state_key": "_last_llm_response",
                "maintain_history": False,
                "is_final_output": True,
            }
        }
    ],
    "edges": [
        {
            "source": "fixed_output",
            "edge_type": "direct",
            "target": "__end__"
        }
    ]
}

# Example agent for user-defined tool call handlers
WORKFLOW_TOOLCALL_EXAMPLE = {
    "name": "toolcall-example",
    "entry_point": "apply_fixed",
    "metadata": {
        "version": "3.0",
        "description": "Fixed-update workflow: always sets CPU limit to 460m. "
                       "No LLM call, purely programmatic.",
        "author": "funpilot"
    },
    "nodes": [
        {
            "name": "apply_fixed",
            "node_type": "tool_call",
            "description": "Set a fixed CPU limit change without any LLM involvement",
            "tool_call_config": {
                "handler_name": "set_fixed_updates",
                "handler_params": {
                    "proposed_changes": [
                        {
                            "control_knob": "spec.template.spec.containers.resource.limits.cpu",
                            "current_value": "unknown",
                            "new_value": "460m",
                            "rationale": "Fixed CPU limit adjustment to 460m."
                        }
                    ],
                    "analysis": "Applying fixed CPU limit update to 460m as configured in workflow definition.",
                    "expected_impact": "CPU limit will be set to 460m for the target revision."
                }
            }
        }
    ],
    "edges": [
        {
            "source": "apply_fixed",
            "edge_type": "direct",
            "target": "__end__"
        }
    ]
}

# Example agent for user-defined tool call handlers and custom renderers
WORKFLOW_CUSTOM_HANDLER_DEMO = {
    "name": "custom-handler-demo",
    "entry_point": "run_calculator",
    "metadata": {
        "version": "1.0",
        "description": "Demo workflow using a custom handler (calculator) and "
                       "a custom renderer (datetime). Demonstrates the end-to-end "
                       "custom extension mechanism.",
        "author": "funpilot"
    },
    "nodes": [
        {
            "name": "run_calculator",
            "node_type": "tool_call",
            "description": "Invoke the custom 'calculator' handler to evaluate a "
                           "math expression and store the result",
            "tool_call_config": {
                "handler_name": "calculator",
                "handler_params": {
                    "expression": "100 + 200 + 160"
                }
            }
        },
        {
            "name": "propose_with_calc",
            "node_type": "llm_call",
            "description": "LLM call that uses the calculator result and a custom "
                           "datetime placeholder to propose changes",
            "llm_call_config": {
                "prompt_template_key": "custom_handler_demo_node",
                "llm_client_key": "propose_node",
                "message_role": "human",
                "output_state_key": "_last_llm_response",
                "maintain_history": False,
                "is_final_output": True
            }
        }
    ],
    "edges": [
        {
            "source": "run_calculator",
            "edge_type": "direct",
            "target": "propose_with_calc"
        },
        {
            "source": "propose_with_calc",
            "edge_type": "direct",
            "target": "__end__"
        }
    ]
}

# Load agent definitions
ALL_WORKFLOW_DEFINITIONS = [
    WORKFLOW_TRIAGE_PROPOSE_JUDGE,
    WORKFLOW_ONESHOT,
    WORKFLOW_FIXED_UPDATE,
    WORKFLOW_TOOLCALL_EXAMPLE,
    WORKFLOW_CUSTOM_HANDLER_DEMO,
]
for wf_def in ALL_WORKFLOW_DEFINITIONS:
    field_key = f"workflow_definition:{wf_def['name']}"
    redis_client.hset(
        f"{USER_ID}:config:{CONFIG_ID}",
        field_key,
        json.dumps(wf_def, ensure_ascii=False),
    )
    print(f"  loaded workflow definition: {wf_def['name']}")

ALLOWED_CONTROL_KNOBS = {
    "spec.template.spec.containers.resource.limits.cpu",
    "spec.template.spec.containers.resource.limits.memory",
    "containerConcurrency",
    "autoscaling.knative.dev/class",
    "autoscaling.knative.dev/metric",
    "autoscaling.knative.dev/target",
    "autoscaling.knative.dev/target-utilization-percentage",
    "autoscaling.knative.dev/scale-to-zero-pod-retention-period",
    "autoscaling.knative.dev/min-scale",
    "autoscaling.knative.dev/max-scale",
    "autoscaling.knative.dev/scale-down-delay",
    "autoscaling.knative.dev/window",
    "autoscaling.knative.dev/panic-window-percentage",
    "autoscaling.knative.dev/panic-threshold-percentage",
    "autoscaling.knative.dev/initial-scale",
    "autoscaling.knative.dev/activation-scale",
}
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "allowed_control_knobs", json.dumps(list(ALLOWED_CONTROL_KNOBS), ensure_ascii=False))

# Prompt templates
TRIAGE_NODE_PROMPT = """
You are a Senior Site Reliability Engineer (SRE) specializing in Knative serverless architecture.
Your task is to TRIAGE incoming alerts and produce a concise, structured diagnostic record.

## Context
### Revision:
{{.RevisionContext}}

### Alert Context (Current fired alert(s) that triggered this remediation workflow):
{{.AlertContext}}

### Alert History (Fired and resolved alerts for this revision and the last fired alerts for previous revisions):
{{.AlertHistory}}

### Workflow Triggering Semantics
{{.WorkflowTriggeringSemantics}}

### Current Metrics
{{.MetricsContext}}

## Diagnostic Goal
Based on the provided context, identify the most plausible operational pattern behind the current alert state.
Focus on:
- observed traffic and workload behavior,
- relationships among alert activity, revision context, and metrics,
- whether the evidence suggests a stable condition, persistent degradation, oscillatory behavior, saturation, or uncertainty,
- whether available evidence suggests that further automated remediation is unlikely to change the outcome.

Do not prescribe actions.
Do not mention hidden reasoning steps.

## Output Requirements
Return a JSON object with EXACTLY these fields:

1. triage_summary
- 6–7 sentences.
- Concisely describe the observed patterns, supporting evidence, and plausible causal structure.
- Explicitly acknowledge missing, ambiguous, or conflicting evidence where relevant.
- If evidence is insufficient for a confident interpretation, say so directly.
- If pre_stop is true, briefly explain why continued remediation appears unlikely to help.
- No remediation language.

2. pre_stop
- Boolean.
- True only when the provided evidence indicates that continued remediation is unlikely to resolve the issue.
- Otherwise false.
"""

PROPOSE_NODE_PROMPT = """
You are an expert Kubernetes and Knative performance engineer.
Your task is to propose a small set of safe, targeted configuration changes that help resolve the currently fired alert(s).

IMPORTANT:
- Only modify control knobs that are explicitly allowed.
- Base every proposed change on the provided context, configuration, and metrics.
- Prioritize resolving the fired alert(s) first; avoid changes that could worsen the alerted metric.
- Prefer the minimum number of changes needed. In most cases, 1-3 changes are sufficient.
- If the evidence is insufficient, do not guess. Return no changes and explain what is missing.
- If the system appears to be recovering from a recent change, avoid stacking additional changes unless there is clear evidence that the current configuration is still wrong.
- Do not invent knobs, metrics, or unsupported causal claims.
- Output must be valid JSON only, with no markdown or extra text.

## Context

### Revision Context:
{{.RevisionContext}}

### Alert Context:
{{.AlertContext}}

### Triage Summary:
{{.TriageSummary}}

### Current Configuration:
{{.KsvcConfiguration}}

### Current Metrics:
{{.MetricsContext}}

{{.JudgeResults}}

### Allowed Control Knobs:
{{.AvailableControlKnobs}}

## What to do

1. Review the traffic pattern, pod behavior, latency signals, and resource pressure.
2. Identify the most likely root cause(s) of the fired alert(s).
3. Decide whether the data is sufficient to act.
4. If action is warranted, propose the smallest set of configuration changes that directly address the root cause(s).
5. If the system is already recovering, or if the issue is not clearly addressable through Knative configuration, return no changes and explain why.
6. If data is insufficient, return no changes and clearly state which existing metrics need to be re-queried.

## Guidance

- Match changes to root causes, not to generic categories.
- Prefer direct and reversible changes over broad or speculative ones.
- When multiple symptoms are present, focus first on the most likely cause of the active alert.
- Avoid contradictory changes or unnecessary rollouts.
- If proposing scaling-related changes, ensure the recommendation is consistent with observed traffic and pod behavior.
- If proposing resource changes, ensure the recommendation is consistent with observed utilization or throttling signals.
- If proposing no changes, clearly distinguish among:
  - insufficient data,
  - ongoing recovery after a recent change,
  - likely application-level issue not clearly fixable through Knative knobs.

## Output Format

{
  "analysis": "<3-6 sentences summarizing what the metrics show, the most likely root cause(s), and any important uncertainty or missing data.>",
  "proposed_changes": [
    {
      "rationale": "<1-3 sentences explaining which root cause this change addresses and why this value was chosen.>",
      "control_knob": "exact_path_from_allowed_list",
      "current_value": "value_or_unknown",
      "new_value": "recommended_value"
    }
  ],
  "expected_impact": "<Describe the expected improvement. If no changes are proposed, explain whether this is due to insufficient data, ongoing recovery, or likely application-level limitation.>",
  "metric_requests": [
    {
      "metric_name": "<must match an existing metric key from MetricsContext>",
      "query_window_seconds": "<integer>",
      "query_step_seconds": "<integer>",
      "reason": "<what is missing in the current data and why a re-query is needed>"
    }
  ]
}

## Constraints on output

- proposed_changes and metric_requests are mutually exclusive.
- If proposed_changes is non-empty, metric_requests must be [].
- If proposed_changes is empty because more data is needed, metric_requests should specify only metrics already present in MetricsContext.
- If proposed_changes is empty because the system is already recovering or the issue is likely application-level, metric_requests must be [].
"""

JUDGE_NODE_PROMPT = """
You are a Senior Reviewer for automated Knative tuning.

You review configuration changes proposed by an automated proposer agent.
Your job is to validate whether the proposal is safe, evidence-based, coherent with the diagnosis, and likely to improve the fired alerts without causing waste or instability.

IMPORTANT:
- Do NOT invent new knobs or metrics.
- Review only against the metrics, alerts, and context already provided.
- APPROVED is a valid and expected outcome when the proposal is sound.
- Do not override a reasonable proposal merely because a different choice was also possible.
- Only use control knobs from the allowed control knob list.

## Review Principles

1. Focus on diagnosis-prescription coherence.
A good proposal should use knobs that directly address the observed root cause.

2. Use resource-demand estimates rather than transient pod counts.
Observed pod counts may be inflated by autoscaler overshoot or oscillation.
Use workload demand inferred from CPU and utilization data as the sizing anchor.

3. Prefer minimal and sufficient changes.
The proposal should address the alerts with as few changes as necessary.
Avoid redundant or weakly justified knob changes.

4. Check for waste as well as under-sizing.
A proposal should not solve an alert by allocating obviously excessive resources.

5. Resource right-sizing is allowed when it is clearly unrelated to the fired alert and still leaves safe headroom.

## Context

### Revision Context:
{{.RevisionContext}}

### Alert Context:
{{.AlertContext}}

### Triage Summary:
{{.TriageSummary}}

### Current Config:
{{.KsvcConfiguration}}

### Current Metrics:
{{.MetricsContext}}

### Proposed Changes (from proposer):
{{.ProposedChanges}}

### Guardrail Analysis Report:
{{.GuardrailReport}}

### Allowed Control Knobs (ONLY these may be modified):
{{.AvailableControlKnobs}}

## Review Procedure

### Step 1. Form an Independent Assessment
Briefly determine:
- what the metrics show,
- what the likely root cause is,
- whether the alert implies increasing capacity or reducing capacity,
- what knobs you would expect to change.

Also determine whether the triage summary indicates strict performance targets.
Use this to choose a consistent review posture:
- for strict targets, expect more headroom;
- for standard targets, expect tighter efficiency.

### Step 2. Validate Basic Safety
Review the guardrail report and ensure the proposal:
- uses only allowed knobs,
- keeps values in valid formats and ranges,
- avoids incompatible knob combinations,
- results in a valid effective configuration, not just valid individual edits.

### Step 3. Check Diagnosis-Prescription Coherence
Evaluate whether the proposed knobs actually address the diagnosed problem.
Look for:
- oscillation handled without a stable floor,
- timid values that are too small to matter,
- oversized values that create waste,
- unnecessary target or concurrency changes,
- capacity increases for over-provisioning alerts,
- capacity reductions for latency, error, or throttling alerts,
- proposals that change CPU limit without revisiting pod-count assumptions.

### Step 4. Check Evidence
Each proposed change should be supported by specific metrics, alert behavior, or a clear derived estimate.
Do not accept vague claims.
Reasonable inference from incomplete observability is acceptable when the triage summary indicates saturation or observability gaps.

### Step 5. Check Completeness and Minimality
Ensure the proposal:
- addresses the fired alerts,
- does not omit a critical missing knob,
- does not include unnecessary changes,
- stays within a small and focused change budget.

### Step 6. Run Capacity Sanity Check
Independently verify whether the proposal is sized appropriately.

Use current workload demand as the base:
- estimate total CPU demand from current CPU limit, observed utilization, and pod count;
- evaluate the resulting proposal using the effective CPU limit after proposed changes;
- derive whether the effective min-scale and related knobs are consistent with that demand.

Check both sides:
- under-provisioning: the proposal is too small to resolve the alert;
- over-provisioning: the proposal allocates far more total CPU than justified.

When both CPU limit and min-scale are changed, explicitly reason about the resulting total guaranteed CPU budget.

When memory is reduced, verify safe headroom over observed peak usage.

### Step 7. Decide the Verdict
Use:
- APPROVED when the proposal is safe, coherent, evidence-based, and sufficient;
- REVISED when the proposal is directionally correct but needs concrete fixes;
- REJECTED when the diagnosis or prescription is fundamentally unsound.

For REVISED:
- return the complete corrected proposed_changes array,
- keep the proposal minimal,
- ensure your revised version is itself internally consistent and valid.

For REJECTED:
- explain what is wrong and what the proposer should focus on next,
- return an empty proposed_changes array.

For APPROVED:
- keep the proposed_changes exactly as provided.

## Output Format (Valid JSON only, no markdown/backticks)
{
  "verdict": "APPROVED | REJECTED | REVISED",
  "rationale": "<2-4 sentences. Reference specific metrics, alerts, and triage findings. Explain your verdict, what is correct about the proposal and what is wrong or missing. Write as a senior engineer reviewing a PR, not as a checklist.>",
  "feedback": "<If REVISED or REJECTED: concrete, actionable feedback explaining what was changed and why (REVISED) or what the proposer should do differently (REJECTED). If APPROVED: empty string.>",
  "proposed_changes": [
    {
      "rationale": "<1-3 sentences tying change to evidence and root cause.>",
      "control_knob": "exact_path_from_allowed_list",
      "current_value": "value_or_unknown",
      "new_value": "recommended_value"
    }
  ]
}

Rules for proposed_changes in output:
- APPROVED: Copy proposed_changes exactly as-is from the proposer. Do not modify.
- REVISED: Provide the COMPLETE corrected proposed_changes array. You may adjust values, add missing critical knobs, or remove unnecessary ones. Every change must have an updated rationale.
- REJECTED: Set proposed_changes to []. The proposer will re-propose from scratch using your feedback.
"""

PROPOSE_NODE_REJECTED_PROMPT = """
Your previous proposal was rejected by the judge. Please revise your proposal based on the judge's feedback and the current context. You must follow the same requirements to propose a new set of control knob changes.

# Judge Feedback
{{.JudgeFeedback}}

"""

PROPOSE_NODE_NEED_METRICS_PROMPT = """
You or the judge have indicated more metrics are needed to make a confident proposal. The additional metric has been requested, and the metrics context is as follows. You must follow the same requirements to propose a new set of control knob changes.

# Additional Metrics Context
{{.AdditionalMetricsContext}}

"""

ONESHOT_NODE_PROMPT = """
You are an expert Kubernetes and Knative Performance Engineer. Analyze the provided context and directly output targeted configuration changes to resolve the triggered alerts.

IMPORTANT:
- You MUST ONLY modify whitelisted knobs.
- Every change must be justified by provided metrics.
- Output valid JSON only, no markdown, no backticks.
- PRIMARY OBJECTIVE: Resolve the fired alert(s) with minimal risk and cost.

## Context

### Revision Context:
{{.RevisionContext}}

### Alert Context:
{{.AlertContext}}

### Current Configuration:
{{.KsvcConfiguration}}

### Current Metrics:
{{.MetricsContext}}

### Allowed Control Knobs (ONLY these may be modified):
{{.AvailableControlKnobs}}

## Instructions

1. Analyze the metrics and alerts to identify root causes.
2. Propose the minimum set of configuration changes needed to resolve all fired alerts.
3. Output your response in the JSON format below.

## Output Format (Valid JSON only, no markdown/backticks)
{
  "analysis": "<A natural-language paragraph (3-6 sentences) describing what the metrics show, the root cause(s), and your reasoning.>",
  "proposed_changes": [
    {
      "control_knob": "exact_path_from_allowed_list",
      "current_value": "value_or_unknown",
      "new_value": "recommended_value",
      "rationale": "<1-3 sentences explaining why this change is needed.>"
    }
  ],
  "expected_impact": "<What improvement is expected after applying these changes.>"
}
"""

FIXED_UPDATE_NODE_PROMPT = """
You are a system testing agent. Output the following fixed control knob update as valid JSON. Do not add any explanation, markdown, or backticks, output ONLY the JSON object below.

## Current Configuration:
{{.KsvcConfiguration}}

{
  "analysis": "Fixed CPU limit adjustment to 360m for system testing.",
  "proposed_changes": [
    {
      "control_knob": "spec.template.spec.containers.resource.limits.cpu",
      "current_value": "extract this value from the current configuration",
      "new_value": "360m",
      "rationale": "Fixed CPU limit set to 360m for testing purposes."
    }
  ],
  "expected_impact": "CPU limit will be set to 360m for the target revision."
}
"""

redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:triage_node", TRIAGE_NODE_PROMPT.strip())
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:propose_node", PROPOSE_NODE_PROMPT.strip())
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:judge_node", JUDGE_NODE_PROMPT.strip())

redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:propose_node_rejected", PROPOSE_NODE_REJECTED_PROMPT.strip())
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:propose_node_need_metrics", PROPOSE_NODE_NEED_METRICS_PROMPT.strip())
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:oneshot_node", ONESHOT_NODE_PROMPT.strip())
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:fixed_update_node", FIXED_UPDATE_NODE_PROMPT.strip())


CUSTOM_HANDLER_DEMO_PROMPT = """
You are a serverless infrastructure assistant. Your task is to analyze the
information below and propose a single control knob change.

## Context
- Service: {{.ServiceName}}
- Current date/time (from custom renderer): {{.CustomPlaceHolderExample}}
- The custom calculator handler evaluated an expression and the result
  has been stored. Use 460m as the CPU limit value for the proposal.

## Instructions
Based on the above context, output a JSON object with the following structure:
{
  "analysis": "Brief explanation of why this change is needed",
  "proposed_changes": [
    {
      "control_knob": "spec.template.spec.containers.resource.limits.cpu",
      "current_value": "unknown",
      "new_value": "460m",
      "rationale": "Set CPU limit based on calculator result"
    }
  ],
  "expected_impact": "CPU limit set to 460m"
}

Respond with ONLY the JSON object. No markdown, no backticks.
"""
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "prompt_template:custom_handler_demo_node", CUSTOM_HANDLER_DEMO_PROMPT.strip())

GLOBAL_AVAILABLE_CONTROL_KNOB_PROMPT = """
**Available Control Knobs** (use exact paths as control_knob values. If your proposed change includes a knob with `valid values`, ensure the new_value is one of them):
- `spec.template.spec.containers.resource.limits.cpu` - CPU resource limit (default: N/A)
- `spec.template.spec.containers.resource.limits.memory` - Memory resource limit (default: N/A)
- `containerConcurrency` - Maximum concurrent requests (hard limit) per container (default: 0, namely unlimited)
- `autoscaling.knative.dev/class` - Autoscaler class (valid values: kpa.autoscaling.knative.dev, hpa.autoscaling.knative.dev; kpa supports concurrency/rps and hpa supports cpu/memory as scaling metrics) (default: kpa.autoscaling.knative.dev)
- `autoscaling.knative.dev/metric` - Scaling metric (valid values: concurrency, rps, cpu, memory) (default: concurrency)
- `autoscaling.knative.dev/target` - Target value for scaling metric (default: 100; units depend on metric, which are concurrency, rps, cpu/memory utilization percentage)
- `autoscaling.knative.dev/target-utilization-percentage` - Target utilization percentage (ONLY work for concurrency scaling metric and when containerConcurrency is configured with a non-zero value) (default: 70, namely 70%)
- `autoscaling.knative.dev/scale-to-zero-pod-retention-period` - Pod retention period (default: 0s)
- `autoscaling.knative.dev/min-scale` - Minimum number of pods (default: 0, namely scale to zero to save cost)
- `autoscaling.knative.dev/max-scale` - Maximum number of pods (default: 0, namely unlimited)
- `autoscaling.knative.dev/scale-down-delay` - Scale down delay (default: 0s)
- `autoscaling.knative.dev/window` - Autoscaling decision window (default: 60s)
- `autoscaling.knative.dev/panic-window-percentage` - Panic window percentage (default: 10, namely 10%)
- `autoscaling.knative.dev/panic-threshold-percentage` - Panic threshold percentage (default: 200, namely 200%)
- `autoscaling.knative.dev/initial-scale` - Initial number of pods (default: 1)
- `autoscaling.knative.dev/activation-scale` - Activation scale (default: 1)
"""

redis_client.hset(
    f"funpilot:prompt_template",
    "control_knobs",
    json.dumps(
        GLOBAL_AVAILABLE_CONTROL_KNOB_PROMPT.strip(),
        ensure_ascii=False,
    )
)

# Agent-related configurations
GENERAL_CONFIG = {
    "agent_cooldown_period_seconds": 120,
    "agent_blackout_period_seconds": 120,
    "agent_execution_timeout_seconds": 120,
    "alert_history_max_entries": 10,
    "alert_history_ttl_seconds": 604800,
    "agent_workflow_max_iterations": 5,
    "missing_placeholder_policy": "WARN_EMPTY"
}
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "general_config", json.dumps(GENERAL_CONFIG, ensure_ascii=False))

# LLM-related configurations
TRIAGE_NODE_LLM_CONFIG = {
    "llm_base_url": "https://openrouter.ai/api/v1",
    "llm_auth_header": "Authorization",
    "llm_auth_token": "Bearer REPLACE_WITH_VALID_TOKEN",
    "llm_model": "openai/gpt-oss-120b",
    "llm_temperature": 0.0,
}
PROPOSE_NODE_LLM_CONFIG = {
    "llm_base_url": "https://openrouter.ai/api/v1",
    "llm_auth_header": "Authorization",
    "llm_auth_token": "Bearer REPLACE_WITH_VALID_TOKEN",
    "llm_model": "openai/gpt-oss-120b",
    "llm_temperature": 0.0,
}
JUDGE_NODE_LLM_CONFIG = {
    "llm_base_url": "https://openrouter.ai/api/v1",
    "llm_auth_header": "Authorization",
    "llm_auth_token": "Bearer REPLACE_WITH_VALID_TOKEN",
    "llm_model": "openai/gpt-oss-120b",
    "llm_temperature": 0.0,
}

redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "llm_config:triage_node", json.dumps(TRIAGE_NODE_LLM_CONFIG, ensure_ascii=False))
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "llm_config:propose_node", json.dumps(PROPOSE_NODE_LLM_CONFIG, ensure_ascii=False))
redis_client.hset(f"{USER_ID}:config:{CONFIG_ID}", "llm_config:judge_node", json.dumps(JUDGE_NODE_LLM_CONFIG, ensure_ascii=False))


AUTH_USERS = {
    "user-1": "user-1-token",
    "user-2": "user-2-token",
    "app": "app-token",
    "funpilot-enabled": "funpilot-enabled-token",
    "public": "public-token",
}
for uid, tok in AUTH_USERS.items():
    auth_key = f"funpilot:auth:{uid}"
    auth_payload = json.dumps({
        "token": tok,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    redis_client.set(auth_key, auth_payload)
    print(f"  seeded auth token for user: {uid}")

BUILTIN_RENDERERS = [
    {"name": "alert_context", "placeholder": "AlertContext",
     "description": "Renders current alert metadata (name, severity, expression, labels, timestamps)",
     "type": "builtin"},
    {"name": "alert_history", "placeholder": "AlertHistory",
     "description": "Renders historical fired/resolved alert events for the revision",
     "type": "builtin"},
    {"name": "revision_context", "placeholder": "RevisionContext",
     "description": "Renders Knative revision metadata (name, generation, container spec, annotations)",
     "type": "builtin"},
    {"name": "workflow_triggering_semantics", "placeholder": "WorkflowTriggeringSemantics",
     "description": "Renders cooldown/blackout window and triggering semantics context",
     "type": "builtin"},
    {"name": "metrics_context", "placeholder": "MetricsContext",
     "description": "Renders current metric snapshot values from the observability stack",
     "type": "builtin"},
    {"name": "ksvc_configuration", "placeholder": "KsvcConfiguration",
     "description": "Renders the current Knative service configuration (spec, annotations, resources)",
     "type": "builtin"},
    {"name": "available_control_knobs", "placeholder": "AvailableControlKnobs",
     "description": "Renders the whitelist of control knobs the agent is allowed to modify",
     "type": "builtin"},
    {"name": "available_metrics", "placeholder": "AvailableMetrics",
     "description": "Renders the catalog of available metric definitions the agent can query",
     "type": "builtin"},
    {"name": "triage_summary", "placeholder": "TriageSummary",
     "description": "Renders the triage diagnostic summary (set by parse_triage_response handler)",
     "type": "builtin"},
    {"name": "proposed_changes", "placeholder": "ProposedChanges",
     "description": "Renders the JSON list of proposed control knob changes",
     "type": "builtin"},
    {"name": "guardrail_report", "placeholder": "GuardrailReport",
     "description": "Renders guardrail validation results for proposed changes",
     "type": "builtin"},
    {"name": "judge_feedback", "placeholder": "JudgeFeedback",
     "description": "Renders judge verdict, rationale, and feedback text",
     "type": "builtin"},
    {"name": "judge_results", "placeholder": "JudgeResults",
     "description": "Renders full judge response JSON (verdict, feedback, rationale, proposed_changes)",
     "type": "builtin"},
    {"name": "additional_metrics_context", "placeholder": "AdditionalMetricsContext",
     "description": "Renders additional metric query results fetched on demand",
     "type": "builtin"},
    {"name": "service_name", "placeholder": "ServiceName",
     "description": "Renders the target Knative service name",
     "type": "builtin"},
    {"name": "revision_name", "placeholder": "RevisionName",
     "description": "Renders the target revision name",
     "type": "builtin"},
    {"name": "revision_id", "placeholder": "RevisionId",
     "description": "Renders the target revision UUID",
     "type": "builtin"},
    {"name": "user_defined_guardrail", "placeholder": "UserDefinedGuardrail",
     "description": "Renders user-defined guardrail rules as prompt-ready constraint text",
     "type": "builtin"},
]

BUILTIN_HANDLERS = [
    {"name": "normalize_proposal",
     "description": "Parses LLM response as Proposal JSON, normalizes control knob names, "
                    "extracts proposed_changes and metric_requests into state",
     "type": "builtin"},
    {"name": "parse_judge_response",
     "description": "Parses judge LLM response, extracts verdict/feedback/rationale, "
                    "handles REVISED/APPROVED/REJECTED/NEED_METRICS verdicts",
     "type": "builtin"},
    {"name": "parse_triage_response",
     "description": "Parses triage LLM response, extracts triage_summary and pre_stop signal",
     "type": "builtin"},
    {"name": "extract_control_knob_updates",
     "description": "Generic handler: extracts proposed_changes from any LLM JSON response "
                    "into final_proposed_changes (minimal output contract)",
     "type": "builtin"},
    {"name": "set_fixed_updates",
     "description": "Sets final_proposed_changes to a fixed list from handler_params "
                    "(no LLM call needed, purely programmatic)",
     "type": "builtin"},
]

BUILTIN_ROUTERS = [
    {"name": "triage_router",
     "description": "Routes after triage: checks fatal_error and pre_stop signal "
                    "(PROPOSE / PRESTOPPED / STOPPED)",
     "type": "builtin", "kind": "router"},
    {"name": "propose_router",
     "description": "Routes after propose: checks fatal_error, pending_metric_requests, "
                    "iteration limits (GUARDRAIL / NEED_METRICS / STOPPED)",
     "type": "builtin", "kind": "router"},
    {"name": "judge_router",
     "description": "Routes after judge: verdict-based routing with iteration limits "
                    "(APPROVED / REVISED / REJECTED / NEED_METRICS / STOPPED)",
     "type": "builtin", "kind": "router"},
]

now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
for r in BUILTIN_RENDERERS:
    r["created_at"] = now
    r["updated_at"] = now
    redis_client.set(f"funpilot:renderers:__public__:{r['name']}", json.dumps(r, ensure_ascii=False))
    redis_client.sadd("funpilot:renderers_index:__public__", r["name"])
print(f"  seeded {len(BUILTIN_RENDERERS)} built-in renderers")

for h in BUILTIN_HANDLERS:
    h["created_at"] = now
    h["updated_at"] = now
    redis_client.set(f"funpilot:handlers:__public__:{h['name']}", json.dumps(h, ensure_ascii=False))
    redis_client.sadd("funpilot:handlers_index:__public__", h["name"])
# Also seed routers as handlers (they appear in handler list for discoverability)
for r in BUILTIN_ROUTERS:
    r["created_at"] = now
    r["updated_at"] = now
    redis_client.set(f"funpilot:handlers:__public__:{r['name']}", json.dumps(r, ensure_ascii=False))
    redis_client.sadd("funpilot:handlers_index:__public__", r["name"])
print(f"  seeded {len(BUILTIN_HANDLERS)} built-in handlers + {len(BUILTIN_ROUTERS)} built-in routers")

print("\nAll configurations loaded successfully.")
