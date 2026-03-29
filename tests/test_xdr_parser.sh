#!/bin/bash
# Test script for XDR parser
# SPDX-License-Identifier: AGPL-3.0-or-later

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Resolve paths relative to repo root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PARSER="$REPO_ROOT/xdr_parser.py"
OUTPUT_DIR="$SCRIPT_DIR/test_output"
VERBOSE=0

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        -p|--parser)
            PARSER="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Test files in order of complexity
BASIC_TESTS=(
    "$SCRIPT_DIR/simplest.x"
    "$SCRIPT_DIR/struct_basic.x"
    "$SCRIPT_DIR/arrays.x"
    "$SCRIPT_DIR/typedef.x"
    "$SCRIPT_DIR/union.x"
    "$SCRIPT_DIR/optional.x"
    "$SCRIPT_DIR/rpc_simple.x"
    "$SCRIPT_DIR/rpc_complex.x"
    "$SCRIPT_DIR/comprehensive.x"
    "$SCRIPT_DIR/edge_cases.x"
)

# XDR files needed to build the rpc/ package
BUILD_TESTS=(
    "$REPO_ROOT/rpc.x"
    "$REPO_ROOT/gss.x"
)

total_tests=0
passed_tests=0
failed_tests=0

echo "XDR Parser Test Suite"
echo "===================="
echo "Parser: $PARSER"
echo "Output: $OUTPUT_DIR"
echo ""

run_test() {
    local test_file=$1
    local test_name=$(basename "$test_file" .x)
    
    total_tests=$((total_tests + 1))
    
    echo -n "Testing $test_file ... "
    
    if [ ! -f "$test_file" ]; then
        echo -e "${YELLOW}SKIP${NC} (file not found)"
        return
    fi
    
    # Run parser
    if [ $VERBOSE -eq 1 ]; then
        if "$PARSER" "$test_file" > "$OUTPUT_DIR/${test_name}.log" 2>&1; then
            echo -e "${GREEN}PASS${NC}"
            passed_tests=$((passed_tests + 1))
        else
            echo -e "${RED}FAIL${NC}"
            failed_tests=$((failed_tests + 1))
            echo "  Error log: $OUTPUT_DIR/${test_name}.log"
            if [ $VERBOSE -eq 1 ]; then
                cat "$OUTPUT_DIR/${test_name}.log"
            fi
        fi
    else
        if "$PARSER" "$test_file" > "$OUTPUT_DIR/${test_name}.log" 2>&1; then
            echo -e "${GREEN}PASS${NC}"
            passed_tests=$((passed_tests + 1))
        else
            echo -e "${RED}FAIL${NC}"
            failed_tests=$((failed_tests + 1))
            echo "  Error log: $OUTPUT_DIR/${test_name}.log"
        fi
    fi
}

echo "Syntax Tests:"
echo "-------------"
for test in "${BASIC_TESTS[@]}"; do
    run_test "$test"
done

echo ""
echo "Build XDR Files:"
echo "----------------"
for test in "${BUILD_TESTS[@]}"; do
    run_test "$test"
done

echo ""
echo "===================="
echo "Test Summary"
echo "===================="
echo "Total:  $total_tests"
echo -e "Passed: ${GREEN}$passed_tests${NC}"
echo -e "Failed: ${RED}$failed_tests${NC}"
echo ""

if [ $failed_tests -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
