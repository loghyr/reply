#!/bin/bash
# Test matrix - run parser with different options
# SPDX-License-Identifier: AGPL-3.0-or-later

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PARSER="$REPO_ROOT/xdr_parser.py"

echo "XDR Parser Test Matrix"
echo "======================"

# Test basic file with both languages
for lang in python c; do
    echo ""
    echo "Testing language: $lang"
    echo "----------------------"

    for test in "$SCRIPT_DIR"/simplest.x "$SCRIPT_DIR"/union.x "$SCRIPT_DIR"/rpc_simple.x; do
        if [ -f "$test" ]; then
            echo -n "  $(basename $test) ... "
            if $PARSER --lang $lang $test > /dev/null 2>&1; then
                echo "✓"
            else
                echo "✗ FAILED"
            fi
        fi
    done
done

# Test build XDR files
echo ""
echo "Testing build XDR files (Python only)"
echo "--------------------------------------"

for test in "$REPO_ROOT"/rpc.x "$REPO_ROOT"/gss.x; do
    if [ -f "$test" ]; then
        echo -n "  $(basename $test) ... "
        if $PARSER --lang python $test > /dev/null 2>&1; then
            echo "✓"
        else
            echo "✗ FAILED"
        fi
    fi
done
