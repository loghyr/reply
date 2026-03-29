/* Test RPC with complex types */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

struct add_args {
    int a;
    int b;
};

struct add_result {
    int status;
    int sum;
};

program CALC_PROG {
    version CALC_V1 {
        void NULL(void) = 0;
        add_result ADD(add_args) = 1;
    } = 1;
} = 100001;
