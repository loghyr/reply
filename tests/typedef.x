/* Test typedef declarations */
/* SPDX-License-Identifier: AGPL-3.0-or-later */

typedef int file_handle;
typedef string filename<255>;
typedef opaque file_data<>;

struct file {
    file_handle handle;
    filename name;
    file_data contents;
};
