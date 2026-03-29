# Makefile for reply XDR/RPC toolkit
# SPDX-License-Identifier: AGPL-3.0-or-later

PARSER = ./xdr_parser.py
TEST_DIR = tests
OUTPUT_DIR = tests/test_output
LANG ?= python

# Test files
TESTS = \
	$(TEST_DIR)/simplest.x \
	$(TEST_DIR)/struct_basic.x \
	$(TEST_DIR)/arrays.x \
	$(TEST_DIR)/typedef.x \
	$(TEST_DIR)/union.x \
	$(TEST_DIR)/optional.x \
	$(TEST_DIR)/rpc_simple.x \
	$(TEST_DIR)/rpc_complex.x \
	$(TEST_DIR)/comprehensive.x \
	$(TEST_DIR)/edge_cases.x

.PHONY: all clean test test-python test-c generate-rpc help

all: test

help:
	@echo "reply XDR/RPC toolkit Makefile"
	@echo "=============================="
	@echo ""
	@echo "Targets:"
	@echo "  test           - Parse all test XDR files"
	@echo "  test-python    - Generate Python code from all tests"
	@echo "  test-c         - Generate C code from all tests"
	@echo "  generate-rpc   - Regenerate rpc/ package from rpc.x and gss.x"
	@echo "  clean          - Remove generated files"
	@echo ""

$(OUTPUT_DIR):
	mkdir -p $(OUTPUT_DIR)

test: $(OUTPUT_DIR)
	@echo "Running XDR Parser Test Suite..."
	@for test in $(TESTS); do \
		echo -n "  $$test ... "; \
		if $(PARSER) $$test > $(OUTPUT_DIR)/$$(basename $$test .x).log 2>&1; then \
			echo "PASS"; \
		else \
			echo "FAIL"; \
			cat $(OUTPUT_DIR)/$$(basename $$test .x).log; \
			exit 1; \
		fi; \
	done
	@echo "All tests passed!"

test-python: $(OUTPUT_DIR)
	@echo "Generating Python code..."
	@for test in $(TESTS); do \
		echo "  $$test ..."; \
		$(PARSER) --lang python --output-dir $(OUTPUT_DIR) $$test || exit 1; \
	done
	@echo "Validating syntax..."
	@for f in $(OUTPUT_DIR)/*_const.py $(OUTPUT_DIR)/*_type.py $(OUTPUT_DIR)/*_pack.py; do \
		python3 -c "import ast; ast.parse(open('$$f').read())" || exit 1; \
	done
	@echo "All Python output is valid!"

test-c: $(OUTPUT_DIR)
	@echo "Generating C code..."
	@for test in $(TESTS); do \
		echo "  $$test ..."; \
		$(PARSER) --lang c --output-dir $(OUTPUT_DIR) $$test || exit 1; \
	done

generate-rpc:
	$(PARSER) --lang python --output-dir rpc rpc.x
	$(PARSER) --lang python --output-dir rpc gss.x

clean:
	rm -rf $(OUTPUT_DIR)
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete
