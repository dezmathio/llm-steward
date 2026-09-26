"""
Unit Tests for LLM Gateway Kit
==============================
These tests don't require a running gateway.
"""

import pytest
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCustomRecognizers:
    """Test custom PII recognizers."""
    
    @pytest.fixture(autouse=True)
    def skip_if_no_presidio(self):
        """Skip tests if presidio is not installed."""
        pytest.importorskip("presidio_analyzer")
    
    def test_employee_id_pattern(self):
        """Test employee ID pattern matching."""
        from guardrails.custom_recognizers import EmployeeIDRecognizer
        
        recognizer = EmployeeIDRecognizer()
        
        # Test valid patterns
        valid_ids = ["EMP-1234", "EMP-12345", "EMP-123456"]
        for emp_id in valid_ids:
            results = recognizer.analyze(emp_id, ["EMPLOYEE_ID"])
            assert len(results) > 0, f"Should match {emp_id}"
        
        # Test invalid patterns
        invalid_ids = ["EMP-123", "EMP1234", "EMPLOYEE-1234"]
        for emp_id in invalid_ids:
            results = recognizer.analyze(emp_id, ["EMPLOYEE_ID"])
            assert len(results) == 0, f"Should not match {emp_id}"
    
    def test_project_code_pattern(self):
        """Test project code pattern matching."""
        from guardrails.custom_recognizers import ProjectCodeRecognizer
        
        recognizer = ProjectCodeRecognizer()
        
        # Test valid patterns
        valid_codes = ["PROJ-ENG-2024", "PROJ-MKT-1234", "PROJ-HR-0001"]
        for code in valid_codes:
            results = recognizer.analyze(code, ["PROJECT_CODE"])
            assert len(results) > 0, f"Should match {code}"
    
    def test_api_key_pattern(self):
        """Test API key pattern matching."""
        from guardrails.custom_recognizers import APIKeyRecognizer
        
        recognizer = APIKeyRecognizer()
        
        # Test OpenAI-style keys
        openai_key = "sk-" + "a" * 48
        results = recognizer.analyze(openai_key, ["API_KEY"])
        assert len(results) > 0, "Should match OpenAI-style key"
        
        # Test AWS access key
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        results = recognizer.analyze(aws_key, ["API_KEY"])
        assert len(results) > 0, "Should match AWS-style key"


class TestCallbackHandler:
    """Test the observability callback handler."""
    
    @pytest.fixture(autouse=True)
    def skip_if_no_litellm(self):
        """Skip tests if litellm is not installed."""
        pytest.importorskip("litellm")
    
    def test_hash_api_key(self):
        """Test API key hashing."""
        from guardrails.custom_callback_handler import hash_api_key
        
        key1 = "sk-test-key-12345"
        key2 = "sk-test-key-12345"
        key3 = "sk-different-key"
        
        hash1 = hash_api_key(key1)
        hash2 = hash_api_key(key2)
        hash3 = hash_api_key(key3)
        
        assert hash1 == hash2, "Same keys should produce same hash"
        assert hash1 != hash3, "Different keys should produce different hashes"
        assert len(hash1) == 16, "Hash should be 16 characters"
    
    def test_truncate_and_redact(self):
        """Test text truncation."""
        from guardrails.custom_callback_handler import truncate_and_redact
        
        short_text = "Hello world"
        long_text = "A" * 500
        
        assert truncate_and_redact(short_text) == short_text
        assert len(truncate_and_redact(long_text)) == 203  # 200 + "..."
        assert truncate_and_redact("") == ""


class TestEvalFramework:
    """Test the evaluation framework."""
    
    def test_eval_case_creation(self):
        """Test creating eval cases."""
        from evals.gateway_eval import EvalCase
        
        case = EvalCase(
            id="test_case",
            category="basic",
            prompt="Say hello",
            expected_contains=["hello", "hi"],
        )
        
        assert case.id == "test_case"
        assert case.category == "basic"
        assert "hello" in case.expected_contains
    
    def test_eval_suite_creation(self):
        """Test creating an eval suite."""
        from evals.gateway_eval import EvalSuite, EvalCase
        
        suite = EvalSuite("test_suite")
        
        case1 = EvalCase(id="case1", category="basic", prompt="Test 1")
        case2 = EvalCase(id="case2", category="code", prompt="Test 2")
        
        suite.add_case(case1)
        suite.add_case(case2)
        
        assert len(suite.cases) == 2
        assert suite.cases[0].id == "case1"
    
    def test_threshold_loading(self):
        """Test loading thresholds."""
        from evals.gateway_eval import EvalSuite
        import tempfile
        import yaml
        
        # Create temp threshold file
        thresholds = {"thresholds": {"default": 0.5, "code": 0.7}}
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(thresholds, f)
            temp_path = f.name
        
        suite = EvalSuite("test")
        suite.load_thresholds(temp_path)
        
        assert suite.get_threshold("code") == 0.7
        assert suite.get_threshold("unknown") == 0.5  # default
        
        # Cleanup
        Path(temp_path).unlink()
    
    def test_basic_eval_suite_creation(self):
        """Test creating the basic eval suite."""
        from evals.gateway_eval import create_basic_eval_suite
        
        suite = create_basic_eval_suite()
        
        assert suite.name == "basic"
        assert len(suite.cases) > 0
        
        # Check categories
        categories = set(c.category for c in suite.cases)
        assert "basic" in categories
        assert "code" in categories


class TestCLI:
    """Test CLI utilities."""
    
    def test_cli_module_imports(self):
        """Test that CLI module can be imported."""
        # This mainly tests syntax errors
        from cli import gateway_cli
        
        assert hasattr(gateway_cli, "main")
        assert hasattr(gateway_cli, "cmd_team_create")
        assert hasattr(gateway_cli, "cmd_key_create")


class TestConfig:
    """Test configuration files."""
    
    def test_litellm_config_valid_yaml(self):
        """Test that LiteLLM config is valid YAML."""
        import yaml
        
        config_path = Path("config/litellm_config.yaml")
        assert config_path.exists(), "Config file should exist"
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        assert "model_list" in config
        assert "general_settings" in config
    
    def test_env_example_exists(self):
        """Test that .env.example exists."""
        env_path = Path(".env.example")
        assert env_path.exists(), ".env.example should exist"
        
        content = env_path.read_text()
        assert "LITELLM_MASTER_KEY" in content
        assert "OPENAI_API_KEY" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
