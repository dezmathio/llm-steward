"""
Gateway Evaluation Tests
========================
Run with: pytest evals/test_evals.py --eval-mode -v
"""

import pytest
from pathlib import Path
from .gateway_eval import GatewayEvalClient, EvalSuite, EvalCase, create_basic_eval_suite


class TestGatewayEvals:
    """Evaluation tests that run through the gateway."""
    
    @pytest.fixture
    def client(self, gateway_url, eval_model):
        """Create an eval client."""
        return GatewayEvalClient(
            gateway_url=gateway_url,
            model=eval_model,
        )
    
    @pytest.fixture
    def suite(self):
        """Create the test suite."""
        suite = create_basic_eval_suite()
        
        # Load thresholds if available
        threshold_path = Path("evals/thresholds.yaml")
        if threshold_path.exists():
            suite.load_thresholds(str(threshold_path))
        
        return suite
    
    def test_gateway_health(self, client, eval_mode):
        """Test that the gateway is reachable."""
        if not eval_mode:
            pytest.skip("Not in eval mode")
        
        import httpx
        response = httpx.get(f"{client.gateway_url}/health")
        assert response.status_code == 200
    
    def test_basic_completion(self, client, eval_mode):
        """Test that basic completions work."""
        if not eval_mode:
            pytest.skip("Not in eval mode")
        
        result = client.complete("Say hello")
        assert result["success"], f"Completion failed: {result.get('error')}"
        assert result["response"], "Empty response"
    
    def test_eval_suite_basic(self, client, suite, eval_mode):
        """Run the basic evaluation suite."""
        if not eval_mode:
            pytest.skip("Not in eval mode")
        
        results = suite.run(client)
        
        print(f"\n{'='*60}")
        print(f"Eval Suite: {results['suite']}")
        print(f"{'='*60}")
        print(f"Overall Score: {results['overall_score']:.2%}")
        print(f"Passed: {results['passed_cases']}/{results['total_cases']}")
        print(f"\nCategory Scores:")
        for cat, score in results['category_scores'].items():
            threshold = suite.get_threshold(cat)
            status = "✓" if results['category_passed'][cat] else "✗"
            print(f"  {status} {cat}: {score:.2%} (threshold: {threshold:.2%})")
        
        # Check category thresholds
        for cat, passed in results['category_passed'].items():
            if not passed:
                score = results['category_scores'][cat]
                threshold = suite.get_threshold(cat)
                pytest.fail(
                    f"Category '{cat}' score {score:.2%} below threshold {threshold:.2%}"
                )
    
    @pytest.mark.parametrize("category", ["basic", "code", "factual"])
    def test_eval_category(self, client, suite, eval_mode, category):
        """Test individual categories."""
        if not eval_mode:
            pytest.skip("Not in eval mode")
        
        # Filter cases for this category
        category_cases = [c for c in suite.cases if c.category == category]
        if not category_cases:
            pytest.skip(f"No cases for category: {category}")
        
        scores = []
        for case in category_cases:
            result = client.run_eval(case)
            scores.append(result.score)
            
            print(f"\n  Case: {case.id}")
            print(f"  Score: {result.score:.2%}")
            if result.error:
                print(f"  Error: {result.error}")
        
        avg_score = sum(scores) / len(scores)
        threshold = suite.get_threshold(category)
        
        assert avg_score >= threshold, \
            f"Category '{category}' avg score {avg_score:.2%} below threshold {threshold:.2%}"


class TestEvalFromFile:
    """Tests that load eval cases from files."""
    
    @pytest.fixture
    def client(self, gateway_url, eval_model):
        return GatewayEvalClient(gateway_url=gateway_url, model=eval_model)
    
    def test_load_eval_cases(self, client, eval_mode):
        """Test loading and running eval cases from file."""
        if not eval_mode:
            pytest.skip("Not in eval mode")
        
        cases_path = Path("evals/cases/test_cases.yaml")
        if not cases_path.exists():
            pytest.skip("No test cases file found")
        
        suite = EvalSuite("file_based")
        suite.add_cases_from_file(str(cases_path))
        suite.load_thresholds("evals/thresholds.yaml")
        
        results = suite.run(client)
        
        print(f"\nFile-based Eval Results:")
        print(f"  Score: {results['overall_score']:.2%}")
        print(f"  Passed: {results['passed_cases']}/{results['total_cases']}")
        
        assert results['overall_passed'], "Eval suite failed"
