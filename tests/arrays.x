/* Test fixed and variable arrays */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

const MAXNAME = 255;

struct file_info {
    string name<MAXNAME>;        /* variable string with max */
    opaque data<>;               /* variable opaque */
    int permissions[3];          /* fixed array */
};
