/* Test basic struct with primitive types */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

struct point {
    int x;
    int y;
};

struct rectangle {
    point top_left;
    point bottom_right;
};
