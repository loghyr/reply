/* Test edge cases and tricky syntax */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

/* Single-value enum */
enum empty_enum {
    ONLY_ONE = 0
};

/* Nested inline structures */
struct outer {
    struct inner_struct {
        int value;
    } nested;
    int other;
};

/* Multiple case values pointing to same arm (fall-through) */
enum color {
    RED = 1,
    GREEN = 2,
    BLUE = 3,
    YELLOW = 4
};

union multi_case switch (color c) {
    case RED:
    case GREEN:
        int warm_value;
    case BLUE:
        int cool_value;
    default:
        void;
};

/* Void in various contexts */
union optional_int switch (bool present) {
    case TRUE:
        int value;
    case FALSE:
        void;
};

/* long and unsigned long (aliases for int/unsigned int) */
struct long_types {
    long state;
    unsigned long flags;
};

/* struct keyword as type prefix in declarations */
struct inner_thing {
    int x;
};

struct uses_struct_prefix {
    struct inner_thing thing;
    string name<255>;
};

/* typedef struct pointer (linked list pattern) */
typedef struct list_node *list_ptr;

struct list_node {
    int value;
    list_ptr next;
};

/* Preprocessor directives (should be skipped) */
#ifdef RPC_HDR
%#define SOME_CONSTANT 42
#endif

/* Passthrough lines inside enum body */
enum big_enum {
    VAL_A = 1,
    VAL_B = 2,
%
%/* section break */
%
    VAL_C = 3,
    VAL_D = 4
};

/* Python keyword as field name (from, class, import, etc.) */
struct rename_args {
    string from<1024>;
    string to<1024>;
};

/* struct keyword in procedure return and arg types */
program EDGE_PROG {
    version EDGE_V1 {
        void NULL(void) = 0;
        struct uses_struct_prefix GET(struct inner_thing) = 1;
    } = 1;
} = 999999;
