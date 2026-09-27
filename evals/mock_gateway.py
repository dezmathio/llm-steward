#!/usr/bin/env python3
"""
Mock LLM Gateway Server for CI Testing
=======================================
A minimal HTTP server that mimics the LiteLLM proxy API for eval testing.
Returns canned responses without any LLM calls.

Usage:
    python evals/mock_gateway.py &
    pytest evals/test_evals.py --eval-mode --gateway-url=http://localhost:4000
"""

import json
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler


class MockGatewayHandler(BaseHTTPRequestHandler):
    """Handle mock gateway requests."""
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
    
    def _send_json(self, data: dict, status: int = 200):
        """Send a JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health" or self.path == "/health/liveliness":
            self._send_json({"status": "healthy"})
        elif self.path == "/health/readiness":
            self._send_json({"status": "healthy", "db": "Not connected"})
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def do_POST(self):
        """Handle POST requests."""
        if "/chat/completions" in self.path:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            
            try:
                request = json.loads(body)
                messages = request.get("messages", [])
                prompt = messages[-1].get("content", "") if messages else ""
                
                # Generate a mock response based on the prompt
                response_text = self._generate_response(prompt)
                
                response = {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request.get("model", "fake/echo"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": response_text,
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": len(prompt.split()),
                        "completion_tokens": len(response_text.split()),
                        "total_tokens": len(prompt.split()) + len(response_text.split()),
                    },
                }
                self._send_json(response)
                
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON"}, 400)
        else:
            self._send_json({"error": "Not found"}, 404)
    
    def _generate_response(self, prompt: str) -> str:
        """Generate a mock response based on the prompt."""
        prompt_lower = prompt.lower()
        
        # Match specific test case expectations from create_basic_eval_suite()
        if prompt_lower == "say hello":
            return "Hello! How can I help you today?"
        
        if "list three colors" in prompt_lower or "three colors" in prompt_lower:
            return "red\nblue\ngreen"
        
        # Match test cases from test_cases.yaml
        if "greeting" in prompt_lower or "hello" in prompt_lower:
            return "Hello! How can I help you today?"
        
        if "count" in prompt_lower and "1 to 5" in prompt_lower:
            return "1, 2, 3, 4, 5"
        
        if "json" in prompt_lower and "name" in prompt_lower and "value" in prompt_lower:
            return '{"name": "example", "value": 42}'
        
        if "python" in prompt_lower and "function" in prompt_lower and "add" in prompt_lower:
            return "def add(a, b):\n    return a + b"
        
        if "python" in prompt_lower and "list" in prompt_lower and "even" in prompt_lower:
            return "[i for i in range(0, 11, 2)]"
        
        if "capital" in prompt_lower and "france" in prompt_lower:
            return "Paris"
        
        if "largest planet" in prompt_lower:
            return "Jupiter is the largest planet in our solar system."
        
        if "hack" in prompt_lower and "bank" in prompt_lower:
            return "I can't help with that. Unauthorized access to financial systems is illegal and unethical."
        
        if "markdown" in prompt_lower and "list" in prompt_lower and "programming" in prompt_lower:
            return "- Python\n- JavaScript\n- Go"
        
        if "steps" in prompt_lower and "coffee" in prompt_lower:
            return "1. Boil water\n2. Add coffee grounds\n3. Pour and enjoy"
        
        # Default response
        return "This is a mock response for CI testing."


def run_server(port: int = 4000):
    """Run the mock gateway server."""
    server = HTTPServer(("", port), MockGatewayHandler)
    print(f"Mock gateway running on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    run_server(port)
