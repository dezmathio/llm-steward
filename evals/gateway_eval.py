"""
LLM Gateway Eval Framework
==========================
A pytest-based evaluation framework for testing LLM responses through the gateway.

Usage:
    pytest evals/ --eval-mode --gateway-url=http://localhost:4000

Features:
    - Category-based test organization
    - Per-category threshold configuration
    - Support for ground truth comparisons
    - Integration with CI/CD pipelines
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml


@dataclass
class EvalCase:
    """A single evaluation test case."""
    id: str
    category: str
    prompt: str
    expected: str | None = None
    expected_contains: list[str] | None = None
    expected_not_contains: list[str] | None = None
    ground_truth: str | None = None
    custom_scorer: Callable[[str, str], float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result of a single evaluation."""
    case: EvalCase
    response: str
    score: float
    passed: bool
    latency_ms: int
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class GatewayEvalClient:
    """Client for running evaluations through the gateway."""
    
    def __init__(
        self,
        gateway_url: str = "http://localhost:4000",
        api_key: str | None = None,
        model: str = "fake/echo",
        timeout: float = 30.0,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.api_key = api_key or os.environ.get("LITELLM_MASTER_KEY", "sk-master-key-change-me")
        self.model = model
        self.timeout = timeout
    
    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def complete(self, prompt: str, model: str | None = None) -> dict[str, Any]:
        """Send a completion request to the gateway."""
        import time
        
        start = time.time()
        
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.gateway_url}/v1/chat/completions",
                headers=self._get_headers(),
                json={
                    "model": model or self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                },
            )
            
        latency_ms = int((time.time() - start) * 1000)
        
        if response.status_code != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}",
                "latency_ms": latency_ms,
            }
        
        data = response.json()
        content = ""
        if data.get("choices"):
            choice = data["choices"][0]
            if choice.get("message"):
                content = choice["message"].get("content", "")
        
        return {
            "success": True,
            "response": content,
            "latency_ms": latency_ms,
            "usage": data.get("usage", {}),
        }
    
    def run_eval(self, case: EvalCase) -> EvalResult:
        """Run a single evaluation case."""
        result = self.complete(case.prompt)
        
        if not result["success"]:
            return EvalResult(
                case=case,
                response="",
                score=0.0,
                passed=False,
                latency_ms=result["latency_ms"],
                error=result["error"],
            )
        
        response = result["response"]
        score, details = self._score_response(case, response)
        
        return EvalResult(
            case=case,
            response=response,
            score=score,
            passed=score >= 0.5,  # Default threshold
            latency_ms=result["latency_ms"],
            details=details,
        )
    
    def _score_response(self, case: EvalCase, response: str) -> tuple[float, dict[str, Any]]:
        """Score a response against the expected output."""
        details: dict[str, Any] = {}
        scores = []
        
        # Custom scorer takes precedence
        if case.custom_scorer:
            score = case.custom_scorer(response, case.ground_truth or case.expected or "")
            return score, {"method": "custom_scorer"}
        
        # Exact match
        if case.expected:
            match = response.strip().lower() == case.expected.strip().lower()
            scores.append(1.0 if match else 0.0)
            details["exact_match"] = match
        
        # Contains check
        if case.expected_contains:
            response_lower = response.lower()
            contains_scores = []
            for term in case.expected_contains:
                found = term.lower() in response_lower
                contains_scores.append(1.0 if found else 0.0)
                details[f"contains_{term}"] = found
            if contains_scores:
                scores.append(sum(contains_scores) / len(contains_scores))
        
        # Not contains check
        if case.expected_not_contains:
            response_lower = response.lower()
            not_contains_scores = []
            for term in case.expected_not_contains:
                not_found = term.lower() not in response_lower
                not_contains_scores.append(1.0 if not_found else 0.0)
                details[f"not_contains_{term}"] = not_found
            if not_contains_scores:
                scores.append(sum(not_contains_scores) / len(not_contains_scores))
        
        # Ground truth similarity (basic)
        if case.ground_truth and not scores:
            # Simple word overlap scoring
            response_words = set(response.lower().split())
            truth_words = set(case.ground_truth.lower().split())
            if truth_words:
                overlap = len(response_words & truth_words) / len(truth_words)
                scores.append(min(overlap, 1.0))
                details["word_overlap"] = overlap
        
        # Default: check response is non-empty
        if not scores:
            scores.append(1.0 if response.strip() else 0.0)
            details["has_response"] = bool(response.strip())
        
        final_score = sum(scores) / len(scores) if scores else 0.0
        return final_score, details


class EvalSuite:
    """Collection of evaluation cases organized by category."""
    
    def __init__(self, name: str = "default"):
        self.name = name
        self.cases: list[EvalCase] = []
        self.thresholds: dict[str, float] = {}
    
    def add_case(self, case: EvalCase):
        """Add a test case to the suite."""
        self.cases.append(case)
    
    def add_cases_from_file(self, path: str):
        """Load test cases from a YAML or JSON file."""
        filepath = Path(path)
        
        if filepath.suffix in [".yaml", ".yml"]:
            with open(filepath) as f:
                data = yaml.safe_load(f)
        else:
            with open(filepath) as f:
                data = json.load(f)
        
        for item in data.get("cases", []):
            case = EvalCase(
                id=item.get("id", f"case_{len(self.cases)}"),
                category=item.get("category", "default"),
                prompt=item["prompt"],
                expected=item.get("expected"),
                expected_contains=item.get("expected_contains"),
                expected_not_contains=item.get("expected_not_contains"),
                ground_truth=item.get("ground_truth"),
                metadata=item.get("metadata", {}),
            )
            self.cases.append(case)
    
    def load_thresholds(self, path: str):
        """Load per-category thresholds from a YAML file."""
        filepath = Path(path)
        if filepath.exists():
            with open(filepath) as f:
                data = yaml.safe_load(f)
            self.thresholds = data.get("thresholds", {})
    
    def get_threshold(self, category: str) -> float:
        """Get the threshold for a category."""
        return self.thresholds.get(category, self.thresholds.get("default", 0.7))
    
    def run(self, client: GatewayEvalClient) -> dict[str, Any]:
        """Run all evaluation cases."""
        results: list[EvalResult] = []
        
        for case in self.cases:
            result = client.run_eval(case)
            threshold = self.get_threshold(case.category)
            result.passed = result.score >= threshold
            results.append(result)
        
        # Aggregate by category
        by_category: dict[str, list[EvalResult]] = {}
        for result in results:
            cat = result.case.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(result)
        
        # Calculate category scores
        category_scores = {}
        category_passed = {}
        
        for cat, cat_results in by_category.items():
            scores = [r.score for r in cat_results]
            avg_score = sum(scores) / len(scores) if scores else 0
            threshold = self.get_threshold(cat)
            
            category_scores[cat] = avg_score
            category_passed[cat] = avg_score >= threshold
        
        # Overall
        all_scores = [r.score for r in results]
        overall_score = sum(all_scores) / len(all_scores) if all_scores else 0
        all_passed = all(category_passed.values()) if category_passed else True
        
        return {
            "suite": self.name,
            "overall_score": overall_score,
            "overall_passed": all_passed,
            "total_cases": len(results),
            "passed_cases": sum(1 for r in results if r.passed),
            "failed_cases": sum(1 for r in results if not r.passed),
            "category_scores": category_scores,
            "category_passed": category_passed,
            "results": results,
        }


def create_basic_eval_suite() -> EvalSuite:
    """Create a basic evaluation suite for testing."""
    suite = EvalSuite("basic")
    
    # Response quality tests
    suite.add_case(EvalCase(
        id="basic_response",
        category="basic",
        prompt="Say hello",
        expected_contains=["hello", "hi"],
    ))
    
    suite.add_case(EvalCase(
        id="instruction_following",
        category="basic",
        prompt="List three colors, one per line",
        expected_contains=["red", "blue", "green"],
    ))
    
    # Code generation tests
    suite.add_case(EvalCase(
        id="code_python_function",
        category="code",
        prompt="Write a Python function that adds two numbers",
        expected_contains=["def", "return"],
    ))
    
    # Factual tests
    suite.add_case(EvalCase(
        id="factual_capital",
        category="factual",
        prompt="What is the capital of France?",
        expected_contains=["Paris"],
    ))
    
    return suite
