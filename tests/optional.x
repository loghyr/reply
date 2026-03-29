/* Test optional/pointer syntax */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

struct node {
    int value;
    node *next;    /* optional next pointer */
};

struct result {
    int status;
    string *error_message;  /* optional error */
};
